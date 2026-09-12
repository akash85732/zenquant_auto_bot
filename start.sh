#!/data/data/com.termux/files/usr/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

pkill -f "python3 host_bot.py"
pkill -f "python3 bot.py"

echo "Starting ZenQuant Auto-Bot in background..."
nohup python3 host_bot.py > host_output.log 2>&1 &

sleep 2
if pgrep -f "bot.py" > /dev/null; then
    echo "✅ ZenQuant Auto-Bot hosted and running successfully!"
    echo "Process ID: $(pgrep -f 'bot.py')"
else
    echo "⚠️ Failed to start bot. Check host_output.log or bot_runner.log"
fi
