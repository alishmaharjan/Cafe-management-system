from django.contrib import admin
from django.urls import include, path
from core import views

urlpatterns = [
    path('', views.pos_view, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('pos/', views.pos_view, name='pos'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('inventory/', views.inventory_view, name='inventory'),
    path('reports/', views.reports_view, name='reports'),
    path('shifts/', views.shifts_view, name='shifts'),
    path('credit/', views.credit_view, name='credit'),
    path('admin/', admin.site.urls),
    path('api/', include('core.urls')),
]
