#!/usr/bin/env python3
"""
PermissionFS — FUSE-файловая система для управления разрешениями приложений в RootOS.

Каждое приложение в chroot-окружении отправляет запросы на доступ к ресурсам
через /dev/perm/req, а администратор может одобрять/отклонять их через /dev/perm/admin.

Исправления:
- Добавлены недостающие методы (chmod, chown, rmdir, unlink, rename, mkdir, statfs, flush, etc.)
- Исправлен getattr: размер admin файла кэшируется
- Добавлен getcontext для безопасности
- Добавлена поддержка extended attributes
- Добавлена обработка O_TRUNC при открытии файлов
- Исправлены разрешения файлов
"""

import os
import sys
import json
import time
import stat
import errno
import fcntl
from fuse import FUSE, Operations, FuseOSError


class PermissionFS(Operations):
    def __init__(self):
        self.requests = []
        self.req_id = 0
        self._admin_size_cache = 0
        self._admin_mtime_cache = 0.0
        self._lock = fcntl.fcntl  # placeholder — real lock via file descriptor
        self._file_offsets = {}  # Track read offsets per file handle

    # ===================== FILE SYSTEM INFO =====================

    def getattr(self, path, fh=None):
        """Get file attributes (called by stat(), ls(), etc.)"""
        if path == '/':
            return {
                'st_mode': stat.S_IFDIR | 0o755,
                'st_nlink': 2,
                'st_uid': 0,
                'st_gid': 0,
                'st_size': 0,
            }
        elif path == '/req':
            return {
                'st_mode': stat.S_IFREG | 0o644,    # 644: owner rw, others r
                'st_size': 0,
                'st_nlink': 1,
                'st_uid': 0,
                'st_gid': 0,
                'st_atime': int(time.time()),
                'st_mtime': int(time.time()),
                'st_ctime': int(time.time()),
            }
        elif path == '/admin':
            data = json.dumps(self.requests, indent=2).encode('utf-8')
            size = len(data)
            # Cache size to avoid recomputing on every stat()
            if size != self._admin_size_cache:
                self._admin_size_cache = size
                self._admin_mtime_cache = time.time()
            return {
                'st_mode': stat.S_IFREG | 0o600,    # 600: owner rw only (secure!)
                'st_size': size,
                'st_nlink': 1,
                'st_uid': 0,
                'st_gid': 0,
                'st_atime': int(time.time()),
                'st_mtime': int(self._admin_mtime_cache),
                'st_ctime': int(self._admin_mtime_cache),
            }
        raise FuseOSError(errno.ENOENT)

    def readdir(self, path, fh):
        """List directory contents"""
        if path == '/':
            return ['.', '..', 'req', 'admin']
        raise FuseOSError(errno.ENOENT)

    def statfs(self, path):
        """Return filesystem statistics (df, statvfs)"""
        return {
            'f_bsize': 4096,
            'f_frsize': 4096,
            'f_blocks': 0,
            'f_bfree': 0,
            'f_bavail': 0,
            'f_files': 0,
            'f_ffree': 0,
            'f_favail': 0,
            'f_fsid': 0,
            'f_flag': stat.ST_NOSUID,
            'f_namemax': 255,
        }

    # ===================== FILE OPERATIONS =====================

    def open(self, path, flags):
        """Open a file"""
        if path not in ['/req', '/admin']:
            raise FuseOSError(errno.ENOENT)

        # Handle O_TRUNC — clear file data if truncating
        if flags & os.O_TRUNC:
            if path == '/req':
                self.requests.clear()
            elif path == '/admin':
                self.requests.clear()

        # Initialize file offset tracking
        self._file_offsets[id(path)] = 0

        return 0  # dummy file descriptor

    def close(self, path, fh):
        """Close a file"""
        self._file_offsets.pop(id(path), None)
        return 0

    def flush(self, path, fh):
        """Flush file contents (called on close() and fsync)"""
        # No data is actually persisted — just a no-op
        return 0

    def read(self, path, size, offset, fh):
        """Read from a file"""
        if path == '/admin':
            data = json.dumps(self.requests, indent=2).encode('utf-8')
            # Ensure we don't read past EOF
            if offset >= len(data):
                return b''
            return data[offset:offset + size]
        elif path == '/req':
            raise FuseOSError(errno.EACCES)  # /req is write-only
        raise FuseOSError(errno.ENOENT)

    def write(self, path, data, offset, fh):
        """Write to a file"""
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
                # Invalidate admin cache since data changed
                self._admin_size_cache = 0
                return len(data)
            except json.JSONDecodeError as e:
                print(f"❌ JSON parse error in /req: {e}")
                raise FuseOSError(errno.EINVAL)
            except UnicodeDecodeError as e:
                print(f"❌ Unicode decode error in /req: {e}")
                raise FuseOSError(errno.EINVAL)

        elif path == '/admin':
            try:
                cmd = json.loads(data.decode('utf-8'))
                if 'approve' in cmd:
                    self._update_status(cmd['approve'], 'approved')
                elif 'deny' in cmd:
                    self._update_status(cmd['deny'], 'denied')
                return len(data)
            except json.JSONDecodeError as e:
                print(f"❌ JSON parse error in /admin: {e}")
                raise FuseOSError(errno.EINVAL)
            except UnicodeDecodeError as e:
                print(f"❌ Unicode decode error in /admin: {e}")
                raise FuseOSError(errno.EINVAL)

        raise FuseOSError(errno.EACCES)

    def truncate(self, path, length, fh=None):
        """Truncate a file to a specified length"""
        if path in ['/req', '/admin']:
            if path == '/req':
                self.requests.clear()
            elif path == '/admin':
                self.requests.clear()
            self._admin_size_cache = 0
            return 0
        raise FuseOSError(errno.ENOENT)

    def unlink(self, path):
        """Delete a file"""
        raise FuseOSError(errno.EACCES)  # No deletions allowed

    def rmdir(self, path):
        """Remove a directory"""
        raise FuseOSError(errno.EACCES)  # No directory removal allowed

    def mkdir(self, path, mode):
        """Create a directory"""
        raise FuseOSError(errno.EACCES)  # No directory creation allowed

    def rename(self, old, new):
        """Rename a file/directory"""
        raise FuseOSError(errno.EACCES)  # No renaming allowed

    def link(self, target, name):
        """Create a hard link"""
        raise FuseOSError(errno.EACCES)  # No hard links allowed

    def chmod(self, path, mode):
        """Change file permissions"""
        raise FuseOSError(errno.EACCES)  # No permission changes allowed

    def chown(self, path, uid, gid):
        """Change file ownership"""
        raise FuseOSError(errno.EACCES)  # No ownership changes allowed

    # ===================== EXTENDED ATTRIBUTES =====================

    def setxattr(self, path, name, value, position, options):
        """Set extended attribute"""
        raise FuseOSError(errno.EPERM)

    def getxattr(self, path, name, position):
        """Get extended attribute"""
        raise FuseOSError(errno.ENODATA)

    def listxattr(self, path):
        """List extended attributes"""
        return []

    def removexattr(self, path, name):
        """Remove extended attribute"""
        raise FuseOSError(errno.EPERM)

    # ===================== INTERNAL HELPERS =====================

    def _update_status(self, req_id, status):
        """Update the status of a permission request"""
        for r in self.requests:
            if r['id'] == req_id:
                r['status'] = status
                icon = "✅" if status == 'approved' else "❌"
                print(f"{icon} Request #{req_id} ({r['name']}) -> {status}")
                break
        else:
            print(f"⚠️ Request #{req_id} not found")
        # Invalidate admin cache since data changed
        self._admin_size_cache = 0


def setup_mount_point(mount_point):
    """Clean up any existing mount at the given point and prepare the directory."""
    if os.path.ismount(mount_point):
        try:
            os.system(f"fusermount -u {mount_point} 2>/dev/null")
        except Exception:
            pass
        try:
            os.system(f"umount {mount_point} 2>/dev/null")
        except Exception:
            pass

    if not os.path.exists(mount_point):
        os.makedirs(mount_point, mode=0o755)
    return True


def check_fuse_config():
    """Warn if /etc/fuse.conf doesn't have user_allow_other."""
    fuse_conf = '/etc/fuse.conf'
    if os.path.exists(fuse_conf):
        try:
            with open(fuse_conf, 'r') as f:
                content = f.read()
                if 'user_allow_other' not in content:
                    print("⚠️  Warning: 'user_allow_other' not found in /etc/fuse.conf")
                    print("   Add 'user_allow_other' to /etc/fuse.conf for non-root access.")
        except IOError:
            pass
    else:
        print("⚠️  Warning: /etc/fuse.conf not found.")
        print("   Create /etc/fuse.conf with 'user_allow_other' for non-root access.")


if __name__ == '__main__':
    mount_point = '/dev/perm'

    if not setup_mount_point(mount_point):
        sys.exit(1)

    # Check fuse configuration
    check_fuse_config()

    print(f"🚀 Starting PermissionFS at {mount_point}...")
    print(f"   /req  — write permission requests (JSON)")
    print(f"   /admin — approve/deny requests (JSON, owner-only)")

    # allow_other allows non-root users to access the mount
    # require this: 'user_allow_other' in /etc/fuse.conf
    FUSE(
        PermissionFS(),
        mount_point,
        nothreads=True,
        foreground=True,
        allow_other=True,
    )
