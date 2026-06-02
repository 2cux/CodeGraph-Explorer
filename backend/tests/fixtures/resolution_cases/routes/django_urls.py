"""Django URL pattern fixtures."""


# Mock Django path/re_path for AST parsing
def path(route: str, view, name: str = None):
    """Django path() — URL pattern."""
    return (route, view)


def re_path(regex: str, view, name: str = None):
    """Django re_path() — regex URL pattern."""
    return (regex, view)


def user_list_view(request):
    """View for listing users."""
    return []


def user_detail_view(request, user_id: int):
    """View for user detail."""
    return {}


urlpatterns = [
    path("/users", user_list_view, name="user-list"),
    path("/users/<int:user_id>", user_detail_view, name="user-detail"),
    re_path(r"^/api/v1/users/$", user_list_view, name="api-user-list"),
]
