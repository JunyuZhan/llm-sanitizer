"""脱敏规则引擎:15 类中文敏感信息识别、占位符映射、精确还原。

设计契约(见 docs/开发文档.md 与 docs/需求文档.md):
- token 格式 `[类别_序号]`,同一原文跨请求复用同一 token(FR-3)
- 类别可配置:disabled_categories 过滤规则(FR-15)
- 只做精确回填还原;事件不落明文;持久化原子写 + chmod 600(FR-8)
- 纯标准库,零第三方依赖(ADR-1)
"""

from __future__ import annotations  # Python 3.9 兼容(PEP 604 联合注解延迟求值)

import json
import os
import re
import tempfile
from collections import defaultdict

# ---------------------------------------------------------------------------
# 姓氏库与停用词(姓名 / 上下文类规则共用)
# ---------------------------------------------------------------------------
SURNAMES = set(
    "王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘"
    "于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江"
    "尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤常温康施文牛樊葛邢安齐"
    "易乔伍庞颜倪庄聂章鲁岳翟殷詹申欧耿关兰焦俞左柳甘祝包宁尚符舒阮柯纪梅童凌毕"
    "单季裴霍涂成苗谷盛曲翁冉骆蓝路游辛靳管柴蒙鲍华喻祁蒲房滕屈饶解牟艾尤阳时穆"
    "农司卓古吉缪简车项连芦麦褚娄窦戚岑景党宫费卜冷晏席卫米柏宗瞿桂全佟应臧闵苟"
    "邬边卞姬师敖糜郜璩谈茅利隋温"
)

# 姓名/机构向左扩展时的常见误伤前缀(命中即截断扩展)
STOP_WORDS = {
    "认为", "请求", "表示", "主张", "陈述", "说明", "需要", "希望", "应当", "可以",
    "我们", "他们", "你们", "这个", "那个", "本案", "经查", "查明", "判决", "裁定",
    "根据", "依照", "综上", "据此", "因此", "但是", "同时", "以及", "或者", "对于",
}

# 省份/直辖市简称(公司名称、司法机关、车牌、案号共用)
PROV_SHORT = "京津冀晋蒙辽吉黑沪苏浙皖闽赣鲁豫鄂湘粤桂琼渝川贵云藏陕甘青宁新"

# ---------------------------------------------------------------------------
# 规则定义:(模式或函数, 类别id)
# 顺序即优先级:先收集的匹配在重叠时优先;身份证/信用代码等长格式先于短格式。
# ---------------------------------------------------------------------------
# 18 位身份证:前 17 位数字 + 末位数字或 X(含校验和与生日校验,校验失败按"疑似"仍脱敏)
_ID18 = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
# 15 位老证:第 7-12 位需构成合法日期(YYMMDD)
_ID15 = re.compile(r"(?<!\d)\d{15}(?!\d)")
# 统一社会信用代码:18 位,排除 I/O/Z/S/V,且必须含字母(纯数字 18 位不构成)
_USCC = re.compile(r"(?<![0-9A-Za-z])[0-9A-HJ-NPQRTUWXY]{18}(?![0-9A-Za-z])")


def _find_uscc(text: str):
    for m in _USCC.finditer(text):
        s = m.group(0)
        if any(c in "ABCDEFGHJKLMNPRTUVWXY" for c in s):
            yield (m.start(), m.end(), s)
# 手机号
_MOBILE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
# 座机:区号 3-4 位(0 开头)+ 7-8 位号码,横线可选
_LANDLINE = re.compile(r"(?<!\d)0\d{2,3}-?\d{7,8}(?!\d)")
# 邮箱
_EMAIL = re.compile(r"(?<![0-9A-Za-z_.+-])[0-9A-Za-z_.+-]+@[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)+(?![0-9A-Za-z-])")
# 银行卡号:16-19 位数字,需通过 Luhn 校验(函数规则,见 _luhn_valid)
_BANK_CAND = re.compile(r"(?<!\d)\d{16,19}(?!\d)")
# 车牌:省简称 + 大写字母 + 5-6 位(蓝牌 5 位 / 新能源 6 位)
_PLATE = re.compile(
    r"(?<![0-9A-Za-z\u4e00-\u9fa5])[" + PROV_SHORT + r"][A-Z][A-HJ-NP-Z0-9]{5,6}(?![0-9A-Za-z])"
)
# 案号:(年份)+ 机关简称 + 法院代号 + 程序词 + 序号 + 号
_CASE_NO = re.compile(
    r"（\d{4}）[" + PROV_SHORT + r"][0-9A-Za-z\u4e00-\u9fa5]{0,8}?"
    r"(民初|民终|刑初|刑终|行初|行终|执|仲|民特|商初|调|破|再|监)\d{1,8}号"
)
# 护照 / 通行证等证件号
_ID_PASSPORT = re.compile(r"(?<![0-9A-Za-z])([EG]\d{8}|P\d{7}|C\d{8}|T\d{8})(?![0-9A-Za-z])")
# 密钥 / 令牌:常见前缀格式
_SECRET_PREFIX = re.compile(
    r"(?<![0-9A-Za-z])(sk-[A-Za-z0-9_\-]{16,64}|ghp_[A-Za-z0-9]{30,60}|"
    r"AIza[A-Za-z0-9_\-]{30,50}|xox[baprs]-[A-Za-z0-9\-]{10,80})(?![0-9A-Za-z])"
)
# 密钥 / 令牌:字段值形式(password/token/secret/api_key = "值")
_SECRET_FIELD = re.compile(
    r"(?i)(?<![0-9A-Za-z])(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*"
    r"['\"]?[A-Za-z0-9_\-@#$%^&*!]{8,64}['\"]?"
)
# 出生日期:强上下文 + 日期
_BIRTH = re.compile(
    r"(出生日期|出生年月|生日|生于|出生于)\s*[:：]?\s*"
    r"(\d{4}年\d{1,2}月\d{1,2}日|\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?)"
)
# 地址:强上下文 + 取值(截断到标点)
_ADDRESS = re.compile(
    r"(住址|住所地|户籍地|现住址|居住地|联系地址|收货地址)\s*[:：]?\s*"
    r"([^，。；;、\n\r]{4,40})"
)
# 公司名称:组织形式关键词向左扩展(至少 2 字字号)
_COMPANY = re.compile(
    r"[\u4e00-\u9fa5A-Za-z0-9]{2,24}?"
    r"(有限公司|有限责任公司|股份有限公司|集团有限公司|控股有限公司|股份公司|分公司|"
    r"集团|合作社|银行|医院|研究院|事务所)"
)
# 司法机关名称:关键词向左扩展(行政区划/机构前缀)
_ORG = re.compile(
    r"[\u4e00-\u9fa5]{2,12}?"
    r"(人民法院|人民检察院|检察院|公安局|公安分局|派出所|仲裁委员会|仲裁委|司法局|"
    r"律师事务所|律所|监狱|看守所)"
)
# 姓名:角色上下文 + 可选冒号/空白 + 姓氏库 + 停用词(函数规则,见 _find_names)
_NAME_CTX = re.compile(
    r"(原告|被告|法定代表人|委托诉讼代理人|委托代理人|诉讼代理人|审判长|审判员|书记员|"
    r"申请人|被申请人|上诉人|被上诉人|申诉人|被申诉人|第三人|甲方|乙方|丙方|丁方|"
    r"联系人|经办人|代理人|负责人)"
    r"(?:[:：\s]*)([\u4e00-\u9fa5]{2,4})"
)


# ---------------------------------------------------------------------------
# 校验辅助
# ---------------------------------------------------------------------------
def _luhn_valid(digits: str) -> bool:
    """银行卡 Luhn 校验:从右往左,偶数位翻倍并减 9。"""
    total = 0
    double = False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if double:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        double = not double
    return total % 10 == 0


_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECK = "10X98765432"


def _id18_valid(s: str) -> bool:
    """18 位身份证校验和 + 生日合法性。校验失败仍按"疑似"脱敏。"""
    if len(s) != 18:
        return False
    if not s[:17].isdigit():
        return False
    total = sum(int(s[i]) * _ID_WEIGHTS[i] for i in range(17))
    return _ID_CHECK[total % 11] == s[17].upper()


def _id15_valid(s: str) -> bool:
    """15 位老证:第 7-12 位构成合法 YYMMDD。"""
    try:
        import datetime

        y = int(s[6:8]) + 1900
        datetime.date(y, int(s[8:10]), int(s[10:12]))
        return True
    except ValueError:
        return False


def _date_looks_valid(ymd: str) -> bool:
    """粗略校验 8 位生日是否合法(如 19900101)。"""
    try:
        import datetime

        datetime.date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]))
        return True
    except ValueError:
        return False


def _is_valid_id18(s: str) -> bool:
    """18 位形如身份证:生日合法(校验和失败也按疑似脱敏)。"""
    return _date_looks_valid(s[6:14])


def _is_valid_id15(s: str) -> bool:
    return _id15_valid(s)


# ---------------------------------------------------------------------------
# 匹配收集
# ---------------------------------------------------------------------------
def _find_secret_fields(text: str):
    """字段值形式的密钥:仅收集,值中不含中文(避免误伤自然语言)。"""
    for m in _SECRET_FIELD.finditer(text):
        value = m.group(0)
        if re.search(r"[\u4e00-\u9fa5]", value):
            continue
        yield (m.start(), m.end(), value)


def _find_names(text: str):
    """姓名:上下文词 + 2-4 汉字,首字必须命中姓氏库,且整体非停用词。"""
    for m in _NAME_CTX.finditer(text):
        name = m.group(2)
        if name in STOP_WORDS or name[:2] in STOP_WORDS:
            continue
        if name[0] in SURNAMES:
            yield (m.start(2), m.end(2), name)


def _find_bank_accounts(text: str):
    """银行卡号:Luhn 校验通过才命中(防误伤普通长数字)。"""
    for m in _BANK_CAND.finditer(text):
        if _luhn_valid(m.group(0)):
            yield (m.start(), m.end(), m.group(0))


def _find_id18(text: str):
    for m in _ID18.finditer(text):
        s = m.group(0)  # 保留原文大小写(还原保真,P3)
        if _is_valid_id18(s):
            yield (m.start(), m.end(), s)


def _find_id15(text: str):
    for m in _ID15.finditer(text):
        s = m.group(0)
        if _is_valid_id15(s):
            yield (m.start(), m.end(), s)


def _strip_stop_prefix(text: str, start: int, keyword_start: int) -> int:
    """向左扩展后的起点若以停用词结尾,截回关键词处。"""
    span = text[start:keyword_start]
    for w in STOP_WORDS:
        if span.endswith(w):
            return keyword_start
    return start


def _trim_org_company(m, keys):
    """匹配串若以停用词开头(如"认为人民法院"),把起点推进到关键词处;
    否则保留整个匹配串(前缀是字号/行政区划,必须一并脱敏)。"""
    s = m.group(0)
    pos = None
    for k in keys:
        i = s.find(k)
        if i >= 0:
            pos = i if pos is None else min(pos, i)
    if pos is None or pos == 0:
        return (m.start(), m.end(), s)
    prefix = s[:pos]
    for w in STOP_WORDS:
        if prefix.endswith(w):
            return (m.start() + pos, m.end(), s[pos:])
    return (m.start(), m.end(), s)


_COMPANY_KEYS = (
    "有限公司", "有限责任公司", "股份有限公司", "集团有限公司", "控股有限公司",
    "股份公司", "分公司", "集团", "合作社", "银行", "医院", "研究院", "事务所",
)
_ORG_KEYS = (
    "人民法院", "人民检察院", "检察院", "公安局", "公安分局", "派出所", "仲裁委员会",
    "仲裁委", "司法局", "律师事务所", "律所", "监狱", "看守所",
)


def _find_company(text: str):
    for m in _COMPANY.finditer(text):
        yield _trim_org_company(m, _COMPANY_KEYS)


def _find_org(text: str):
    for m in _ORG.finditer(text):
        yield _trim_org_company(m, _ORG_KEYS)


# ---------------------------------------------------------------------------
# 规则表:每个元素为 (匹配迭代器生成函数, 类别id)
# 匹配函数输入 text,输出 (start, end, matched_text) 迭代
# ---------------------------------------------------------------------------
def _iter_matches(rule, text: str):
    fn = rule[0]
    if callable(fn):
        yield from fn(text)
    else:
        for m in fn.finditer(text):
            yield (m.start(), m.end(), m.group(0))


# 规则顺序即优先级(重叠时先声明者胜)
RULES = [    (_find_id18, "身份证号"),
    (_find_id15, "身份证号"),
    (_find_uscc, "统一社会信用代码"),
    (_find_bank_accounts, "银行账号"),
    (_MOBILE, "手机号"),
    (_LANDLINE, "座机号"),
    (_EMAIL, "邮箱"),
    (_PLATE, "车牌号"),
    (_CASE_NO, "案号"),
    (_ID_PASSPORT, "证件号"),
    (_SECRET_PREFIX, "密钥令牌"),
    (_find_secret_fields, "密钥令牌"),
    (_find_company, "公司名称"),
    (_find_org, "司法机关"),
    (_BIRTH, "出生日期"),
    (_ADDRESS, "地址"),
    (_find_names, "姓名"),
]

# 全部类别(按首次出现顺序去重),供类别开关/配置使用
ALL_CATEGORIES = list(dict.fromkeys(cat for _, cat in RULES))


# ---------------------------------------------------------------------------
# 引擎
# ---------------------------------------------------------------------------
class Masker:
    """双向映射 + 类别计数器 + 类别开关。"""

    def __init__(self, disabled_categories=None):
        self.reverse: dict[str, str] = {}          # 原文 -> token
        self.mapping: dict[str, str] = {}          # token -> 原文
        self.counters: dict[str, int] = defaultdict(int)  # 类别 -> 序号
        self.disabled = set(disabled_categories or ())

    # -- 映射 ------------------------------------------------------------
    def token_for(self, category: str, text: str) -> str:
        if text in self.reverse:
            return self.reverse[text]
        self.counters[category] += 1
        token = f"[{category}_{self.counters[category]}]"
        self.reverse[text] = token
        self.mapping[token] = text
        return token

    # -- 脱敏 ------------------------------------------------------------
    def mask(self, text: str) -> str:
        """按规则优先级收集匹配,去重叠后统一替换为占位符。"""
        hits = []  # (start, end, category, matched)
        for fn, category in RULES:
            if category in self.disabled:
                continue
            for start, end, matched in _iter_matches((fn, category), text):
                if end <= start:
                    continue
                hits.append((start, end, category, matched))
        # 按位置排序;重叠时保留先收集的(规则优先级)
        hits.sort(key=lambda h: (h[0], h[1]))
        accepted = []
        last_end = -1
        for h in hits:
            if h[0] >= last_end:
                accepted.append(h)
                last_end = h[1]
        # 从后往前替换,保持位置有效
        out = list(text)
        # 直接构建新串
        parts = []
        cursor = 0
        for start, end, category, matched in accepted:
            if start < cursor:
                continue
            parts.append(text[cursor:start])
            parts.append(self.token_for(category, matched))
            cursor = end
        parts.append(text[cursor:])
        return "".join(parts)

    # -- 持久化 ----------------------------------------------------------
    def load_mapping(self, data: dict) -> None:
        """恢复映射(重启后 token 不漂移)。data 形如 {"[姓名_1]": "张三"}。"""
        if not isinstance(data, dict):
            return
        for token, original in data.items():
            if isinstance(token, str) and isinstance(original, str):
                self.mapping[token] = original
                self.reverse.setdefault(original, token)
                category = token[1 : token.rfind("_")] if "_" in token else "?"
                seq = token[token.rfind("_") + 1 : -1]
                if seq.isdigit():
                    self.counters[category] = max(self.counters[category], int(seq))

    def save(self, path) -> None:
        """原子写 + chmod 600(敏感文件统一落盘要求,FR-8/D7)。"""
        path = str(path)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".map-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.mapping, f, ensure_ascii=False, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass


def mask_text(text: str, masker: Masker | None = None) -> tuple[str, Masker]:
    """脱敏入口(库 API)。返回 (脱敏文本, masker)。"""
    if masker is None:
        masker = Masker()
    return masker.mask(text), masker


def restore_text(text: str, mapping: dict) -> str:
    """精确回填:按 token 长度降序替换,避免 [姓名_1] 与 [姓名_10] 前缀冲突。"""
    if not mapping:
        return text
    for token in sorted(mapping, key=len, reverse=True):
        original = mapping[token]
        if token in text:
            text = text.replace(token, original)
    return text
