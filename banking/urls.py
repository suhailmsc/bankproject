from django.urls import path

from . import views

app_name = "banking"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("accounts/new/", views.open_account, name="open_account"),
    path("accounts/<int:pk>/", views.account_detail, name="account_detail"),
    path("accounts/<int:pk>/add-demo-funds/", views.fund_account, name="fund_account"),
    path("transfer/", views.transfer, name="transfer"),
    path("transfer/review/", views.transfer_review, name="transfer_review"),
    path("receipt/<str:reference>/", views.receipt, name="receipt"),
    path("beneficiaries/", views.beneficiaries, name="beneficiaries"),
    path("beneficiaries/add/", views.beneficiary_add, name="beneficiary_add"),
    path("beneficiaries/<int:pk>/remove/", views.beneficiary_delete, name="beneficiary_delete"),
    path("activity/", views.activity, name="activity"),
]
