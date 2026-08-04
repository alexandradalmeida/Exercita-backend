from rest_framework.views import exception_handler


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        response.data = {
            "erro": True,
            "codigo": response.status_code,
            "detalhes": response.data,
        }

    return response
