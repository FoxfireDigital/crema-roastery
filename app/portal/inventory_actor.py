from contextvars import ContextVar

current_actor=ContextVar('green_inventory_actor',default=None)


class InventoryActorMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        token=current_actor.set(request.user.pk if request.user.is_authenticated else None)
        try:return self.get_response(request)
        finally:current_actor.reset(token)
