"""Geocodificacao (morada -> coordenadas).

TODO: a integracao com o Google Maps (ou equivalente) exige chave de API e contrato. Nada aqui
assume URLs ou formatos reais: `GeocodingGoogle` fica por implementar e o backend por omissao
(`none`) nao geocodifica, obrigando a indicar latitude/longitude. `GeocodingMock` serve para testes.
"""
from decouple import config


class GeocodingGateway:
    def geocodificar(self, morada):
        """Devolve (latitude, longitude) como floats, ou None se nao encontrar."""
        raise NotImplementedError


class GeocodingNenhum(GeocodingGateway):
    def geocodificar(self, morada):
        return None


class GeocodingGoogle(GeocodingGateway):
    def geocodificar(self, morada):
        raise NotImplementedError("TODO: integrar com a API de geocodificacao (requer chave).")


class GeocodingMock(GeocodingGateway):
    """Tabela fixa para desenvolvimento/testes."""
    CONHECIDAS = {"luanda": (-8.8383, 13.2344), "benguela": (-12.5763, 13.4055)}

    def geocodificar(self, morada):
        for nome, coordenadas in self.CONHECIDAS.items():
            if nome in morada.lower():
                return coordenadas
        return None


def obter_geocoder():
    backend = config("GEOCODING_BACKEND", default="none")
    return {"google": GeocodingGoogle, "mock": GeocodingMock}.get(backend, GeocodingNenhum)()
