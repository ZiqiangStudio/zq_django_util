import csv
from datetime import timedelta

from django.conf import settings
from django.contrib import admin
from django.db.models import Count
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _

from zq_django_util.logs import models


@admin.register(models.ExceptionLog)
class ExceptionLogAdmin(admin.ModelAdmin):
    list_per_page = 20  # 每页显示条数
    list_display = [
        "exp_id",
        "exception_type",
        "method",
        "url",
        "ip",
        "user",
        "create_time",
    ]
    list_display_links = ["exp_id", "exception_type"]
    search_fields = ["exp_id", "exception_type", "ip", "url", "user"]
    list_filter = ["exception_type", "method", "url", "user"]
    ordering = ["-id"]


class ExportCsvMixin:
    def export_as_csv(self, request, queryset):
        meta = self.model._meta
        field_names = [field.name for field in meta.fields]

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename={}.csv'.format(meta)
        writer = csv.writer(response)

        writer.writerow(field_names)
        for obj in queryset:
            row = writer.writerow([getattr(obj, field) for field in field_names])

        return response

    export_as_csv.short_description = "Export Selected"


class SlowAPIsFilter(admin.SimpleListFilter):
    title = _('API Performance')

    # Parameter for the filter that will be used in the URL query.
    parameter_name = 'api_performance'

    def __init__(self, request, params, model, model_admin):
        super().__init__(request, params, model, model_admin)
        if hasattr(settings, 'DRF_API_LOGGER_SLOW_API_ABOVE'):
            if type(settings.DRF_API_LOGGER_SLOW_API_ABOVE) == int:  # Making sure for integer value.
                # Converting to seconds.
                self._DRF_API_LOGGER_SLOW_API_ABOVE = settings.DRF_API_LOGGER_SLOW_API_ABOVE / 1000
        else:
            self._DRF_API_LOGGER_SLOW_API_ABOVE = 0.5

    def lookups(self, request, model_admin):
        """
        Returns a list of tuples. The first element in each
        tuple is the coded value for the option that will
        appear in the URL query. The second element is the
        human-readable name for the option that will appear
        in the right sidebar.
        """
        slow = 'Slow'
        fast = 'Fast'
        if hasattr(settings, 'DRF_API_LOGGER_SLOW_API_ABOVE'):
            slow += ', >={}ms'.format(settings.DRF_API_LOGGER_SLOW_API_ABOVE)
            fast += ', <{}ms'.format(settings.DRF_API_LOGGER_SLOW_API_ABOVE)
        else:
            slow += ', >=500ms'
            fast += ', <500ms'

        return (
            ('slow', _(slow)),
            ('fast', _(fast)),
        )

    def queryset(self, request, queryset):
        """
        Returns the filtered queryset based on the value
        provided in the query string and retrievable via
        `self.value()`.
        """
        # to decide how to filter the queryset.
        if self.value() == 'slow':
            return queryset.filter(execution_time__gte=self._DRF_API_LOGGER_SLOW_API_ABOVE)
        if self.value() == 'fast':
            return queryset.filter(execution_time__lt=self._DRF_API_LOGGER_SLOW_API_ABOVE)

        return queryset


@admin.register(models.RequestLog)
class RequestLogAdmin(admin.ModelAdmin, ExportCsvMixin):

    actions = ["export_as_csv"]

    def __init__(self, model, admin_site):
        super().__init__(model, admin_site)
        self._DRF_API_LOGGER_TIMEDELTA = 0

        self.list_filter += (SlowAPIsFilter,)
        if hasattr(settings, 'DRF_API_LOGGER_TIMEDELTA'):
            if type(settings.DRF_API_LOGGER_TIMEDELTA) == int:  # Making sure for integer value.
                self._DRF_API_LOGGER_TIMEDELTA = settings.DRF_API_LOGGER_TIMEDELTA

    def added_on_time(self, obj):
        return (obj.added_on + timedelta(minutes=self._DRF_API_LOGGER_TIMEDELTA)).strftime("%d %b %Y %H:%M:%S")

    added_on_time.admin_order_field = 'create_time'
    added_on_time.short_description = 'Create at'

    list_per_page = 20
    list_display = ["method", "url", "ip", "user", "create_time"]
    list_display_links = ["method", "url"]
    search_fields = ["ip", "url", "user"]
    list_filter = ["method", "url", "user"]
    ordering = ["-id"]

    change_list_template = 'charts_change_list.html'
    change_form_template = 'change_form.html'
    date_hierarchy = 'create_time'

    def changelist_view(self, request, extra_context=None):
        response = super(RequestLogAdmin, self).changelist_view(request, extra_context)
        try:
            filtered_query_set = response.context_data["cl"].queryset
        except:
            return response
        analytics_model = filtered_query_set.values('create_time__date').annotate(total=Count('id')).order_by('total')
        status_code_count_mode = filtered_query_set.values('id').values('status_code').annotate(
            total=Count('id')).order_by('status_code')
        status_code_count_keys = list()
        status_code_count_values = list()
        for item in status_code_count_mode:
            status_code_count_keys.append(item.get('status_code'))
            status_code_count_values.append(item.get('total'))
        extra_context = dict(
            analytics=analytics_model,
            status_code_count_keys=status_code_count_keys,
            status_code_count_values=status_code_count_values
        )
        response.context_data.update(extra_context)
        return response

    def get_queryset(self, request):
        drf_api_logger_default_database = 'default'
        if hasattr(settings, 'DRF_API_LOGGER_DEFAULT_DATABASE'):
            drf_api_logger_default_database = settings.DRF_API_LOGGER_DEFAULT_DATABASE
        return super(RequestLogAdmin, self).get_queryset(request).using(drf_api_logger_default_database)

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        if request.GET.get('export', False):
            drf_api_logger_default_database = 'default'
            if hasattr(settings, 'DRF_API_LOGGER_DEFAULT_DATABASE'):
                drf_api_logger_default_database = settings.DRF_API_LOGGER_DEFAULT_DATABASE
            export_queryset = self.get_queryset(request).filter(pk=object_id).using(drf_api_logger_default_database)
            return self.export_as_csv(request, export_queryset)
        return super(RequestLogAdmin, self).changeform_view(request, object_id, form_url, extra_context)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

