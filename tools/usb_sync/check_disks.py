import subprocess
import json

ps_cmd = """
Get-Disk | ForEach-Object {
    [PSCustomObject]@{
        Number = $_.Number
        FriendlyName = $_.FriendlyName
        BusType = $_.BusType
        Size = [math]::Round($_.Size / 1GB, 2)
        PartitionStyle = $_.PartitionStyle
        OperationalStatus = $_.OperationalStatus
    }
} | ConvertTo-Json
"""

res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True)
print("=== DISKS ===")
print(res.stdout)

ps_vol = """
Get-Volume | ForEach-Object {
    [PSCustomObject]@{
        DriveLetter = $_.DriveLetter
        FileSystemLabel = $_.FileSystemLabel
        FileSystem = $_.FileSystem
        DriveType = $_.DriveType
        Size = [math]::Round($_.Size / 1GB, 2)
        SizeRemaining = [math]::Round($_.SizeRemaining / 1GB, 2)
    }
} | ConvertTo-Json
"""
res2 = subprocess.run(["powershell", "-NoProfile", "-Command", ps_vol], capture_output=True, text=True)
print("=== VOLUMES ===")
print(res2.stdout)
