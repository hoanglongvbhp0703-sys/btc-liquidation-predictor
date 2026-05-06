import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from django.urls import path
from dashboard.consumers import TickConsumer

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "btc_dashboard.settings")

django_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_app,
    "websocket": URLRouter([
        path("ws/tick/", TickConsumer.as_asgi()),
    ]),
})
