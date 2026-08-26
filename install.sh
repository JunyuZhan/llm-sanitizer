#!/usr/bin/env bash
# LLM Sanitizer 开机自启安装脚本
#   macOS:  LaunchAgent(用户级 plist)
#   Linux:  systemd 用户级 unit
#   ./install.sh          安装为开机自启
#   ./install.sh --uninstall  移除自启(保留数据目录)
set -euo pipefail

NAME="llm-sanitizer"
DATA_DIR="${LLM_SANITIZER_HOME:-$HOME/.llm-sanitizer}"

uninstall() {
  case "$(uname -s)" in
    Darwin)
      PLIST="$HOME/Library/LaunchAgents/com.llmsanitizer.gateway.plist"
      if [ -f "$PLIST" ]; then
        launchctl unload "$PLIST" 2>/dev/null || true
        rm -f "$PLIST"
        echo "[llm-sanitizer] 已停止并移除 LaunchAgent"
      else
        echo "[llm-sanitizer] 未安装 LaunchAgent"
      fi
      ;;
    Linux)
      if [ -f "$HOME/.config/systemd/user/llm-sanitizer.service" ]; then
        systemctl --user disable --now llm-sanitizer 2>/dev/null || true
        rm -f "$HOME/.config/systemd/user/llm-sanitizer.service"
        systemctl --user daemon-reload 2>/dev/null || true
        echo "[llm-sanitizer] 已停止并移除 systemd 用户服务"
      else
        echo "[llm-sanitizer] 未安装 systemd 服务"
      fi
      ;;
    *)
      echo "[llm-sanitizer] 不支持的系统:$(uname -s)" >&2
      exit 1
      ;;
  esac
  echo "[llm-sanitizer] 数据目录保留:$DATA_DIR(如需彻底清理:rm -rf \"$DATA_DIR\")"
}

install() {
  CMD="$(command -v llm-sanitizer || true)"
  if [ -z "$CMD" ]; then
    PY="$(command -v python3 || true)"
    if [ -n "$PY" ]; then
      CMD="$PY -m llm_sanitizer"
    fi
  fi
  if [ -z "$CMD" ]; then
    echo "[llm-sanitizer] 错误:未找到 llm-sanitizer 或 python3,请先安装" >&2
    exit 1
  fi
  echo "[llm-sanitizer] 将自启命令:$CMD start"

  case "$(uname -s)" in
    Darwin)
      PLIST_DIR="$HOME/Library/LaunchAgents"
      PLIST="$PLIST_DIR/com.llmsanitizer.gateway.plist"
      mkdir -p "$PLIST_DIR"
      # launchd 不按空格分词:ProgramArguments 必须拆成单词数组。
      # 注意:必须用真实换行拼接(双引号内 \n 是字面量,会让 plist 变成非法 XML)。
      ARGS=""
      for part in $CMD start; do
        ARGS="$ARGS
    <string>$part</string>"
      done
      cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.llmsanitizer.gateway</string>
  <key>ProgramArguments</key>
  <array>
${ARGS}  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>EnvironmentVariables</key>
  <dict>
    <key>LLM_SANITIZER_HOME</key><string>$DATA_DIR</string>
  </dict>
</dict>
</plist>
EOF
      # 自检:plist 必须通过 plutil 校验,否则不执行加载(防止坏 plist 上线)
      plutil -lint "$PLIST"
      if [ -z "${LLM_SANITIZER_DRY_RUN:-}" ]; then
        launchctl unload "$PLIST" 2>/dev/null || true
        launchctl load "$PLIST"
        echo "[llm-sanitizer] 已安装 LaunchAgent:$PLIST"
      else
        echo "[llm-sanitizer] DRY-RUN:已生成 $PLIST(未加载)"
      fi
      ;;
    Linux)
      UNIT_DIR="$HOME/.config/systemd/user"
      UNIT="$UNIT_DIR/llm-sanitizer.service"
      mkdir -p "$UNIT_DIR"
      cat > "$UNIT" <<EOF
[Unit]
Description=LLM Sanitizer gateway
After=network.target

[Service]
ExecStart=$CMD start
Restart=on-failure
RestartSec=5
Environment=LLM_SANITIZER_HOME=$DATA_DIR

[Install]
WantedBy=default.target
EOF
      if [ -z "${LLM_SANITIZER_DRY_RUN:-}" ]; then
        systemctl --user daemon-reload
        systemctl --user enable --now llm-sanitizer
        echo "[llm-sanitizer] 已安装 systemd 用户服务:$UNIT"
      else
        echo "[llm-sanitizer] DRY-RUN:已生成 $UNIT(未启用)"
      fi
      ;;
    *)
      echo "[llm-sanitizer] 不支持的系统:$(uname -s)" >&2
      exit 1
      ;;
  esac
  echo "[llm-sanitizer] 完成。看板:http://127.0.0.1:8791 卸载:./install.sh --uninstall"
}

case "${1:-}" in
  --uninstall) uninstall ;;
  *) install ;;
esac
