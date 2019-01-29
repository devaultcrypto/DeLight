#!/bin/bash
set -m
./electron-cash daemon --testnet --dir=/Electron-Cash-SLP &
sleep 5
./electron-cash daemon --testnet --dir=/Electron-Cash-SLP load_wallet
fg %1