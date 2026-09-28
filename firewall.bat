@echo off
rem Run as administrator: opens the web and device (ADMS) ports in Windows Firewall.
netsh advfirewall firewall delete rule name="ZK Attendance Pro" >nul 2>&1
netsh advfirewall firewall add rule name="ZK Attendance Pro" dir=in action=allow protocol=TCP localport=8090,8081,90
echo Done. If you changed the ports in zkpro.ini, edit this file accordingly.
pause
