from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path
from django.contrib.auth.decorators import login_required
from django.views.generic import TemplateView
from portal import views
from portal.planning import planner
from portal.order_import import order_import,review_import,order_visibility,dismiss_selected
from portal.subscriptions import subscriptions
from portal.hours import edit_hours,remove_hours
from portal.production import batch_detail,historical_roasts
from portal.payments import payments,void_payment
from portal.plan_actions import plans,delete_plan,accept_plan
from portal.roast_sheet import save_roast_row,undo_roast_row
from portal.packing import packing_list,save_packing,save_progress
from portal.label_sheets import label_sheets,artwork,reprint_run,update_run
from portal.label_sheets import artwork_print_preview
from portal.green_stock import green_stock_page
from portal.green_review import green_review_action
from portal.batch_removal import delete_batch
from portal.payroll import payroll_page,export_payroll
from portal.artwork_library import library
from portal.shopify import connection_page,callback,refresh
from portal.information_review import information_review
from portal.roasted_stock import stock_page
from portal.product_checks import product_checks
from portal.artwork_decisions import artwork_decision
from portal.history_plans import past_plan,associate_history,move_history_order
from portal.workflow import preview_selection,save_drafts
from portal.wholesale import wholesale_order
from portal.day_review import finish_day
from portal.recovery import recovery_page,download_backup,export_records
from portal.shopify_automatic import receive_event,set_automatic
from portal.help_guide import help_guide
from portal.order_lookup import lookup_order
from portal.plan_completion import close_plan,completed_plan
from portal.appearance import appearance_page
from portal.artisan_profiles import profile_library,profile_detail,profile_download,all_alarm_copies,supplied_alarm_download,prepare_artisan,preparation_detail,preparation_download
from portal.artisan_uploads import upload_profile,upload_batch_log,batch_log_detail,batch_log_download,unlink_batch_log
from portal.shopfloor import supplies,maintenance
from portal.green_forecast import green_forecast_page
from portal.batch_photos import batch_photos,photo_detail,photo_image,unlink_photo
from portal.sourcing import suppliers,purchases,bean_details
from portal.cupping import cupping_page
from portal.instance import setup_page
from portal.stores import connections,refresh_store
from portal.store_csv import csv_import,csv_example
from portal.production_orders import review_production
from portal.batch_combine import combine_batches
urlpatterns=[
    path('plans/<int:pk>/combine/',combine_batches,name='combine_batches'),
    path('imports/<int:pk>/production/',review_production,name='review_production'),
    path('plans/<int:pk>/green-review/',green_review_action,name='green_review_action'),
    path('stores/csv/',csv_import,name='store_csv'),
    path('stores/csv/example/',csv_example,name='store_csv_example'),
    path('stores/',connections,name='store_connections'),
    path('stores/<uuid:pk>/refresh/',refresh_store,name='store_refresh'),
    path('setup/',setup_page,name='roastery_setup'),
    path('suppliers/',suppliers,name='suppliers'),
    path('purchases/',purchases,name='purchases'),
    path('green-beans/<int:pk>/details/',bean_details,name='bean_details'),
    path('cupping/',cupping_page,name='cupping'),
    path('supplies/',supplies,name='supplies'),
    path('roasters/maintenance/',maintenance,name='roaster_maintenance'),
    path('green-beans/forecast/',green_forecast_page,name='green_forecast'),
    path('batches/<int:pk>/photos/',batch_photos,name='batch_photos'),
    path('batch-photos/<uuid:photo_id>/',photo_detail,name='batch_photo_detail'),
    path('batch-photos/<uuid:photo_id>/image/',photo_image,name='batch_photo_image'),
    path('batch-photos/<uuid:photo_id>/thumbnail/',photo_image,{'thumbnail':True},name='batch_photo_thumbnail'),
    path('batch-photos/<uuid:photo_id>/unlink/',unlink_photo,name='batch_photo_unlink'),
    path('artisan/upload/',upload_profile,name='artisan_upload'),
    path('artisan/profiles/<str:key>/upload/',upload_profile,name='artisan_upload_revision'),
    path('batches/<int:pk>/artisan/upload/',upload_batch_log,name='artisan_batch_log_upload'),
    path('artisan/logs/<uuid:log_id>/',batch_log_detail,name='artisan_batch_log'),
    path('artisan/logs/<uuid:log_id>/download/',batch_log_download,name='artisan_batch_log_download'),
    path('artisan/logs/<uuid:log_id>/unlink/',unlink_batch_log,name='artisan_batch_log_unlink'),
    path('artisan/',profile_library,name='artisan_library'),
    path('artisan/alarm-copies/',all_alarm_copies,name='artisan_alarm_copies'),
    path('artisan/supplied-alarm/',supplied_alarm_download,name='artisan_supplied_alarm'),
    path('artisan/profiles/<str:key>/',profile_detail,name='artisan_profile'),
    path('artisan/profiles/<str:key>/<str:kind>/',profile_download,name='artisan_profile_download'),
    path('artisan/prepare/<int:pk>/',prepare_artisan,name='artisan_prepare'),
    path('artisan/preparations/<uuid:preparation_id>/',preparation_detail,name='artisan_preparation'),
    path('artisan/preparations/<uuid:preparation_id>/download/',preparation_download,name='artisan_preparation_download'),
    path('payroll/',payroll_page,name='payroll'),
    path('payroll/export/',export_payroll,name='export_payroll'),
    path('healthz/',views.healthz),
    path('login/',LoginView.as_view(template_name='portal/login.html'),name='login'),
    path('logout/',LogoutView.as_view(),name='logout'),
    path('admin/',admin.site.urls),
    path('',views.home,name='home'),
    path('help/',help_guide,name='help'),
    path('green-beans/',green_stock_page,name='green_stock'),
    path('appearance/',appearance_page,name='appearance'),
    path('information/',information_review,name='information_review'),
    path('information/artwork-match/',artwork_decision,name='artwork_decision'),
    path('products/',product_checks,name='product_checks'),
    path('stock/',stock_page,name='roasted_stock'),
    path('packing/',packing_list,name='packing'),
    path('packing/<int:pk>/',save_packing,name='save_packing'),
    path('packing/<int:pk>/progress/',save_progress,name='packing_progress'),
    path('labels/',label_sheets,name='label_sheets'),
    path('labels/artwork/',library,name='artwork_library'),
    path('labels/artwork/<uuid:asset_id>/preview/',artwork_print_preview,name='artwork_print_preview'),
    path('labels/artwork/<str:asset_id>/',artwork,name='label_artwork'),
    path('labels/runs/<uuid:pk>/pdf/',reprint_run,name='reprint_label_run'),
    path('labels/runs/<uuid:pk>/',update_run,name='update_label_run'),
    path('roasts/<int:pk>/',save_roast_row,name='save_roast_row'),
    path('roasts/<int:pk>/undo/',undo_roast_row,name='undo_roast_row'),
    path('planning/',planner,name='planning'),
    path('plans/',plans,name='plans'),
    path('plans/associate-history/',associate_history,name='associate_history'),
    path('plans/history/orders/<int:pk>/move/',move_history_order,name='move_history_order'),
    path('plans/<int:pk>/drafts/',save_drafts,name='save_drafts'),
    path('plans/<int:pk>/history/',past_plan,name='past_plan'),
    path('plans/<int:pk>/accept/',accept_plan,name='accept_plan'),
    path('plans/<int:pk>/delete/',delete_plan,name='delete_plan'),
    path('plans/<int:pk>/restore/',delete_plan,{'restore':True},name='restore_plan'),
    path('imports/',order_import,name='order_import'),
    path('imports/find/',lookup_order,name='lookup_order'),
    path('plans/<int:pk>/close/',close_plan,name='close_plan'),
    path('plans/<int:pk>/reopen/',close_plan,{'reopen':True},name='reopen_plan'),
    path('plans/<int:pk>/completed/',completed_plan,name='completed_plan'),
    path('wholesale/',wholesale_order,name='wholesale_order'),
    path('finish-day/',finish_day,name='finish_day'),
    path('recovery/',recovery_page,name='recovery'),
    path('recovery/download/',download_backup,name='download_backup'),
    path('recovery/records/',export_records,name='export_records'),
    path('shopify/events/',receive_event,name='shopify_events'),
    path('shopify/automatic/',set_automatic,name='shopify_automatic'),
    path('imports/preview/',preview_selection,name='preview_selection'),
    path('imports/dismiss-selected/',dismiss_selected,name='dismiss_selected'),
    path('imports/<int:pk>/visibility/',order_visibility,name='order_visibility'),
    path('shopify/',connection_page,name='shopify'),
    path('shopify/callback/',callback,name='shopify_callback'),
    path('shopify/refresh/',refresh,name='shopify_refresh'),
    path('imports/<int:pk>/review/',review_import,name='review_import'),
    path('subscriptions/',subscriptions,name='subscriptions'),
    path('clock/',views.clock,name='clock'),
    path('batches/new/',views.new_batch,name='new_batch'),
    path('batches/<int:pk>/',batch_detail,name='batch_detail'),
    path('batches/<int:pk>/delete/',delete_batch,name='delete_batch'),
    path('history/',views.history,name='history'),
    path('history/roasting-sheet/',historical_roasts,name='historical_roasts'),
    path('timesheets/',views.timesheets,name='timesheets'),
    path('timesheets/payments/',payments,name='payments'),
    path('timesheets/payments/<int:pk>/void/',void_payment,name='void_payment'),
    path('timesheets/new/',edit_hours,name='add_hours'),
    path('timesheets/<int:pk>/edit/',edit_hours,name='edit_hours'),
    path('timesheets/<int:pk>/delete/',remove_hours,name='remove_hours'),
    path('timesheets/<int:pk>/restore/',remove_hours,{'restore':True},name='restore_hours'),
    path('timesheets/export/',views.export_timesheets,name='export_timesheets'),
    path('orders/',views.orders,name='orders'),
    path('orders/new/',views.new_order,name='new_order'),
    path('orders/<int:pk>/',views.order_detail,name='order_detail'),
]
