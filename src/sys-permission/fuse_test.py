#!/usr/bin/env python3
import os
import sys
import json
import time
import stat
import errno
from fuse import FUSE, Operations, FuseOSError

class PermissionFS(Operations):
    def __init__(self):
        self.requests = []
        self.req_id = 0

    def getattr(self, path, fh=None):
        if path == '/':
            return {
                'st_mode': (stat.S_IFDIR | 0o755),
                'st_nlink': 2
            }
        elif path == '/req':
            return {
                'st_mode': (stat.S_IFREG | 0o666),  # Read and write permissions
                'st_size': 0,
                'st_nlink': 1
            }
        elif path == '/admin':
            data = json.dumps(self.requests, indent=2).encode('utf-8')
            return {
                'st_mode': (stat.S_IFREG | 0o666),
                'st_size': len(data),
                'st_nlink': 1
            }
        raise FuseOSError(errno.ENOENT)

    def readdir(self, path, fh):
        if path == '/':
            return ['.', '..', 'req', 'admin']
        raise FuseOSError(errno.ENOENT)

    def open(self, path, flags):
        if path not in ['/req', '/admin']:
            raise FuseOSError(errno.ENOENT)
        return 0

    # IMPORTANT: The truncate method is required for proper '>' operator handling in Bash
    def truncate(self, path, length, fh=None):
        if path in ['/req', '/admin']:
            return 0
        raise FuseOSError(errno.ENOENT)

    def read(self, path, size, offset, fh):
        if path == '/admin':
            data = json.dumps(self.requests, indent=2).encode('utf-8')
            return data[offset:offset + size]
        raise FuseOSError(errno.EACCES)

    def write(self, path, data, offset, fh):
        if path == '/req':
            try:
                req = json.loads(data.decode('utf-8'))
                self.req_id += 1
                self.requests.append({
                    'id': self.req_id,
                    'name': req.get('name', 'unknown'),
                    'device': req.get('device', 'unknown'),
                    'time': time.strftime('%H:%M:%S'),
                    'status': 'pending'
                })
                print(f"📨 Request #{self.req_id}: {req.get('name')} -> {req.get('device')}")
                return len(data)
            except Exception as e:
                print(f"❌ Parse error in /req: {e}")
                raise FuseOSError(errno.EINVAL)

        elif path == '/admin':
            try:
                cmd = json.loads(data.decode('utf-8'))
                if 'approve' in cmd:
                    self._update_status(cmd['approve'], 'approved')
                elif 'deny' in cmd:
                    self._update_status(cmd['deny'], 'denied')
                return len(data)
            except Exception as e:
                print(f"❌ Parse error in /admin: {e}")
                raise FuseOSError(errno.EINVAL)

        raise FuseOSError(errno.EACCES)

    def _update_status(self, req_id, status):
        for r in self.requests:
            if r['id'] == req_id:
                r['status'] = status
                icon = "✅" if status == 'approved' else "❌"
                print(f"{icon} Request #{req_id} ({r['name']}) -> {status}")
                break


def setup_mount_point(mount_point):
    if os.path.ismount(mount_point):
        os.system(f"fusermount -u {mount_point} 2>/dev/null || umount {mount_point} 2>/dev/null")

    if not os.path.exists(mount_point):
        os.makedirs(mount_point)
    return True


if __name__ == '__main__':
    mount_point = '/dev/perm'

    if not setup_mount_point(mount_point):
        sys.exit(1)

    print(f"🚀 Starting PermissionFS at {mount_point}...")
    
    # allow_other parameter added for access by non-root users
    FUSE(PermissionFS(), mount_point, nothreads=True, foreground=True, allow_other=True)
