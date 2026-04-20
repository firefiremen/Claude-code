@echo off
schtasks /create /tn "KillWeChat_1120" /tr "taskkill /F /IM WeChat.exe" /sc daily /st 11:20 /f /rl limited
schtasks /create /tn "KillWeChat_1700" /tr "taskkill /F /IM WeChat.exe" /sc daily /st 17:00 /f /rl limited
schtasks /create /tn "KillWeChat_1715" /tr "taskkill /F /IM WeChat.exe" /sc daily /st 17:15 /f /rl limited
if %errorlevel%==0 (
    echo 任务创建成功！无需管理员权限。
) else (
    echo 创建失败，请联系IT或手动添加任务计划。
)
pause
