from fastapi import APIRouter

from .v1.admin import router as admin_router
from .v1.admin_files import router as admin_files_router
from .v1.ai_chat import router as ai_chat_router
from .v1.atp_assets import router as atp_assets_router
from .v1.auth import router as auth_router
from .v1.avatar import router as avatar_router
from .v1.dimension_types import router as dimension_types_router
from .v1.dimensions import router as dimensions_router
from .v1.documents import router as documents_router
from .v1.elevation import router as elevation_router
from .v1.fault_analysis import router as fault_analysis_router
from .v1.fault_recurrence import router as fault_recurrence_router
from .v1.fl_analysis import router as fl_analysis_router
from .v1.flower_monitor import router as flower_monitor_router
from .v1.lightning import router as lightning_router
from .v1.lines import router as lines_router
from .v1.param_category import router as param_category_router
from .v1.scheduled_tasks import router as scheduled_tasks_router
from .v1.system_messages import router as system_messages_router
from .v1.system_params import router as system_params_router
from .v1.task_logs import router as task_logs_router
from .v1.task_monitor import router as task_monitor_router
from .v1.tower_models import router as tower_models_router
from .v1.tower_profiles import router as tower_profiles_router
from .v1.traveling_wave import router as traveling_wave_router
from .v1.users import router as users_router
from .v1.wine import router as wine_router
from .v1.ws import router as ws_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(auth_router)
v1_router.include_router(users_router)
v1_router.include_router(avatar_router)
v1_router.include_router(admin_router)
v1_router.include_router(admin_files_router)
v1_router.include_router(ai_chat_router)
v1_router.include_router(atp_assets_router)
v1_router.include_router(dimensions_router)
v1_router.include_router(dimension_types_router)
v1_router.include_router(documents_router)
v1_router.include_router(task_monitor_router)
v1_router.include_router(task_logs_router)
v1_router.include_router(scheduled_tasks_router)
v1_router.include_router(system_messages_router)
v1_router.include_router(system_params_router)
v1_router.include_router(param_category_router)
v1_router.include_router(elevation_router)
v1_router.include_router(fault_analysis_router)
v1_router.include_router(fault_recurrence_router)
v1_router.include_router(fl_analysis_router)
v1_router.include_router(flower_monitor_router)
v1_router.include_router(lightning_router)
v1_router.include_router(lines_router)
v1_router.include_router(tower_models_router)
v1_router.include_router(tower_profiles_router)
v1_router.include_router(traveling_wave_router)
v1_router.include_router(wine_router)
v1_router.include_router(ws_router)


@v1_router.get("/ping")
def ping() -> dict[str, str]:
    return {"message": "pong"}


api_router = APIRouter()
api_router.include_router(v1_router)