import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def preencher_autor_e_avaliado(apps, schema_editor):
    """As avaliacoes antigas eram do aluno para o PT da sessao."""
    Avaliacao = apps.get_model("core", "Avaliacao")
    for av in Avaliacao.objects.select_related("sessao__aluno", "sessao__personal_trainer"):
        av.autor_id = av.sessao.aluno.utilizador_id
        av.avaliado_id = av.sessao.personal_trainer.utilizador_id
        av.save(update_fields=["autor", "avaliado"])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_sessao_lembrete'),
    ]

    operations = [
        migrations.AddField(
            model_name='avaliacao',
            name='autor',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='avaliacoes_feitas', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='avaliacao',
            name='avaliado',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='avaliacoes_recebidas', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='avaliacao',
            name='classificacao',
            field=models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(5)]),
        ),
        migrations.AlterField(
            model_name='avaliacao',
            name='sessao',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='avaliacoes', to='core.sessao'),
        ),
        migrations.RunPython(preencher_autor_e_avaliado, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='avaliacao',
            name='autor',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='avaliacoes_feitas', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='avaliacao',
            name='avaliado',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='avaliacoes_recebidas', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddConstraint(
            model_name='avaliacao',
            constraint=models.UniqueConstraint(fields=('sessao', 'autor'), name='uma_avaliacao_por_autor_e_sessao'),
        ),
    ]
