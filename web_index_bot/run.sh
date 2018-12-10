#!/usr/bin/env bash

# run.sh - Shell script that wraps around web_index_bot.py if you had
#    to install it to a virtualenv like I did.  This script assumes that you
#    set up the virtualenv the way you're supposed to and didn't tinker with
#    the sandbox too much.  If you did, you're on your own.

# by: The Doctor [412/724/301/703/415][ZS] <drwho at virtadpt dot net>

# Core code.

# Bring in the virtualenv.  Imagine whatever sci-fi sound effects you wish
# as this happens.
source env/bin/activate

# Call the bot with the remaining command line args.
python ./web_index_bot.py $@

# Clean up.
exit 0
