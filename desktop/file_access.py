"""Explain denied local file operations without changing ACLs or deleting user files."""
from pathlib import Path


class TaskFileAccessError(PermissionError):
    def __init__(self, operation, path, cause):
        self.operation = operation
        self.target = str(path)
        self.winerror_code = getattr(cause, 'winerror', None)
        super().__init__(f'{operation}失败：{path}')


def explain_file_error(error, task_path=None):
    if not isinstance(error, PermissionError) and getattr(error, 'winerror', None) not in (5, 32, 33):
        return str(error)
    if isinstance(error, TaskFileAccessError):
        title = f'{error.operation}失败'
        paths = [error.target]
    else:
        title = 'Windows 拒绝访问文件或目录'
        paths = list(dict.fromkeys(str(p) for p in (getattr(error, 'filename', None), getattr(error, 'filename2', None)) if p))
    code = getattr(error, 'winerror_code', None) or getattr(error, 'winerror', None)
    message = title + (f'（WinError {code}）' if code else '')
    if paths:
        message += '：' + ' → '.join(paths)
    else:
        message += '；系统未提供具体文件名'
    if task_path:
        message += '。任务记录：' + str(task_path)
    message += '。请退出其他正在处理同一任务的软件窗口，并确认任务记录不是只读文件、任务目录可写。若被占用的是表格，请关闭 Excel/WPS。若桌面目录持续拒绝写入，可将整个任务文件夹复制到你可写的目录，再加载复制目录中的任务进度.json 继续；保留原目录，不要只移动 JSON。'
    return message
