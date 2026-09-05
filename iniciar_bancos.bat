@echo off
setlocal

cd /d "%~dp0"
echo SQLite nao usa servidor: cada API cria seu banco local automaticamente.
echo Inicie a API desejada com api1\scripts\iniciar.bat ate api4\scripts\iniciar.bat.
endlocal
