@echo off
chcp 65001 >nul
title MaSoThue Crawler

if "%1"=="" goto :help
if "%1"=="install" goto :install
if "%1"=="search" goto :search
if "%1"=="all" goto :all

:help
echo.
echo  MaSoThue.com Crawler
echo  =====================
echo.
echo  Usage:
echo    run install                          Install dependencies
echo    run search [TAX_ID or NAME]          Search by Tax ID or company name
echo    run all                              Crawl ALL companies
echo    run all --province "ho-chi-minh"     Crawl one province
echo    run all --max-pages 5                Limit pages per province
echo.
echo  Options (add after search/all):
echo    --format csv^|excel^|both            Output format (default: both)
echo    --detail                             Fetch full detail per company (slower)
echo    --delay 1.5                          Delay between requests (seconds)
echo.
echo  Examples:
echo    run search 3502569148
echo    run search "Minh Huy"
echo    run all --province "ha-noi" --max-pages 3 --format excel
echo    run all --detail --delay 2
echo.
goto :eof

:install
echo Installing dependencies...
pip install -r requirements.txt
goto :eof

:search
shift
python crawl.py search %1 %2 %3 %4 %5 %6 %7 %8 %9
goto :eof

:all
shift
python crawl.py all %1 %2 %3 %4 %5 %6 %7 %8 %9
goto :eof
