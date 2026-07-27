from django.db import migrations

# Old lifecycle → new lifecycle. shipped/delivered/cancelled/refunded are unchanged.
REMAP = {
    "pending": "draft",
    "paid": "confirmed",
    "fulfilled": "fulfillment",
}


def forwards(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    for old, new in REMAP.items():
        Order.objects.filter(status=old).update(status=new)


def backwards(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    for old, new in REMAP.items():
        Order.objects.filter(status=new).update(status=old)


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0003_alter_order_status_orderstatusevent"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
