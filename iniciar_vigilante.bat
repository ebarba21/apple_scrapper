@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Vigilante stock iPhone 18 Pro Max
python vigilante_stock.py
pause
