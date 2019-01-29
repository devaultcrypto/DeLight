#!/usr/bin/expect -f
set timeout 10
spawn ./electron-cash create --dir=/Electron-Cash-SLP
expect "Password (hit return if you do not wish to encrypt your wallet):"
send "\r"
expect eof