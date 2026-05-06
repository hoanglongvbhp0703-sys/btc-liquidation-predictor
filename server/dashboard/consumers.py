import json
from channels.generic.websocket import AsyncWebsocketConsumer


class TickConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add("tick", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("tick", self.channel_name)

    async def tick_message(self, event):
        await self.send(text_data=json.dumps(event["data"]))
