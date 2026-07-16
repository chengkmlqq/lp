"""Menu-related exceptions for detailed error reporting."""


class MenuValidationError(Exception):
    """Base exception for menu validation errors."""
    def __init__(self, message: str, field: str | None = None):
        self.message = message
        self.field = field
        super().__init__(message)


class EmptyMenuCodeError(MenuValidationError):
    """Raised when menu code is empty."""
    def __init__(self):
        super().__init__("菜单编码不能为空", "code")


class EmptyMenuNameError(MenuValidationError):
    """Raised when menu name is empty."""
    def __init__(self):
        super().__init__("菜单名称不能为空", "name")


class DuplicateMenuCodeError(MenuValidationError):
    """Raised when menu code already exists."""
    def __init__(self, code: str):
        super().__init__(f"菜单编码 '{code}' 已存在", "code")
        self.code = code


class RemovedMenuCodeError(MenuValidationError):
    """Raised when attempting to use a removed menu code."""
    def __init__(self, code: str):
        super().__init__(f"菜单编码 '{code}' 已被系统移除，不能使用", "code")
        self.code = code


class SelfParentError(MenuValidationError):
    """Raised when menu tries to set itself as parent."""
    def __init__(self):
        super().__init__("菜单不能将自己设为父菜单", "parent_id")


class ParentNotFoundError(MenuValidationError):
    """Raised when specified parent menu does not exist."""
    def __init__(self, parent_id: str):
        super().__init__(f"父菜单 '{parent_id}' 不存在", "parent_id")
        self.parent_id = parent_id
