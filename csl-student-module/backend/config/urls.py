"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include

admin.site.site_header = "CSL Skill Matrix Administration"
admin.site.site_title = "CSL Admin Portal"
admin.site.index_title = "CSL Operational Dashboard"

_orig_admin_index = admin.site.index

def custom_admin_index(request, extra_context=None):
    from apps.users.models import User
    from apps.courses.models import Course, Batch
    from apps.activities.models import Activity

    extra_context = extra_context or {}
    extra_context["pending_students_count"] = User.objects.filter(
        role=User.Role.STUDENT, status=User.AccountStatus.PENDING
    ).count()
    extra_context["active_students_count"] = User.objects.filter(
        role=User.Role.STUDENT, status=User.AccountStatus.ACTIVE
    ).count()
    extra_context["total_courses_count"] = Course.objects.filter(is_active=True).count()
    extra_context["total_batches_count"] = Batch.objects.filter(is_active=True).count()
    extra_context["draft_activities_count"] = Activity.objects.filter(status=Activity.Status.DRAFT).count()
    extra_context["active_activities_count"] = Activity.objects.filter(status=Activity.Status.ACTIVE).count()
    return _orig_admin_index(request, extra_context=extra_context)

admin.site.index = custom_admin_index

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('apps.auth_api.urls')),
    path('api/student/', include('apps.users.urls')),
    path('api/student/activities/', include('apps.activities.urls')),
    path('api/assessment/', include('apps.assessments.urls')),
]

