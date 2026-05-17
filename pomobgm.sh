#!/usr/bin/env bash
# pomobgm — YouTube から BGM 用音声を並列ダウンロード
# 使い方:
#   source pomobgm.sh          # .bashrc / .zshrc に追加
#   pomobgm "URL1" "URL2" ...
#
# 保存先: ~/Music/pomodoro-bgm/

pomobgm() {
  local dir="$HOME/Music/pomodoro-bgm"
  mkdir -p "$dir"

  if [ $# -eq 0 ]; then
    echo "使い方: pomobgm \"URL\" \"URL\" ..."
    return 1
  fi

  printf '%s\n' "$@" | xargs -n 1 -P 4 -I {} \
    yt-dlp -x --audio-format mp3 \
      -o "$dir/%(title).200B [%(id)s].%(ext)s" \
      "{}"
}
