import sys
from django.apps import AppConfig

SKIP_CMDS = {"migrate", "makemigrations", "collectstatic", "shell",
             "dbshell", "check", "test", "createsuperuser", "flush"}

class DashboardConfig(AppConfig):
    name          = "dashboard"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        cmd = sys.argv[1] if len(sys.argv) > 1 else ""
        if cmd in SKIP_CMDS:
            return
        from . import broadcaster
        broadcaster.start()
