from __future__ import annotations

from rest_framework import serializers


class RequestUploadSerializer(serializers.Serializer):
    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=100)
    byte_size = serializers.IntegerField(min_value=1)
    financial_account_id = serializers.UUIDField(required=False, allow_null=True)


class ConfirmUploadSerializer(serializers.Serializer):
    #: base64 image data, used only when the storage backend can't presign
    #: (local dev without S3). Optional in every other environment.
    image_base64 = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class ConfirmFieldsSerializer(serializers.Serializer):
    merchant = serializers.CharField(max_length=160, required=False, allow_blank=True)
    amount_minor = serializers.IntegerField(min_value=1, required=False)
    occurred_on = serializers.DateField(required=False, allow_null=True)
    category_id = serializers.UUIDField(required=False, allow_null=True)


class LinkReceiptSerializer(serializers.Serializer):
    financial_account_id = serializers.UUIDField()
    category_id = serializers.UUIDField()
