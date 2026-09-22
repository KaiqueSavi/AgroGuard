"""
AgroGuard IA — Erros de negócio da API (Sprint 3/4)
====================================================

Hierarquia de exceções que carregam o código de negócio, a mensagem em
pt-BR, o status HTTP correspondente e um detalhe opcional. Os handlers em
`agroguard.api.main` convertem qualquer `ErroAgroGuard` na resposta
`ErroOut` com o status HTTP certo — services e rotas apenas levantam a
exceção, nunca formatam a resposta.
"""
from __future__ import annotations

from typing import Any


class ErroAgroGuard(Exception):
    """Base de todos os erros de negócio da API."""

    def __init__(self, codigo: str, mensagem: str, http_status: int, detalhe: Any = None) -> None:
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem
        self.http_status = http_status
        self.detalhe = detalhe


class ErroValidacao(ErroAgroGuard):
    """Payload não passa nas regras de validação de schema."""

    def __init__(self, mensagem: str = "Dados inválidos.", detalhe: Any = None) -> None:
        super().__init__("validacao", mensagem, 422, detalhe)


class Inconsistencia(ErroAgroGuard):
    """Payload é estruturalmente válido, mas inconsistente entre campos."""

    def __init__(self, mensagem: str = "Leitura inconsistente.", detalhe: Any = None) -> None:
        super().__init__("inconsistencia", mensagem, 422, detalhe)


class LeituraDuplicada(ErroAgroGuard):
    """Já existe leitura para o mesmo equip_id + data_hora."""

    def __init__(self, mensagem: str = "Leitura duplicada.", detalhe: Any = None) -> None:
        super().__init__("duplicado", mensagem, 409, detalhe)


class EquipamentoDesconhecido(ErroAgroGuard):
    """equip_id não existe no cadastro da frota."""

    def __init__(self, mensagem: str = "Equipamento desconhecido.", detalhe: Any = None) -> None:
        super().__init__("equip_desconhecido", mensagem, 422, detalhe)


class AssinaturaInvalida(ErroAgroGuard):
    """X-Signature ausente (quando exigida) ou não confere com o payload."""

    def __init__(self, mensagem: str = "Assinatura inválida.", detalhe: Any = None) -> None:
        super().__init__("assinatura", mensagem, 401, detalhe)


class NaoAutenticado(ErroAgroGuard):
    """X-API-Key ausente ou desconhecida."""

    def __init__(self, mensagem: str = "Não autenticado.", detalhe: Any = None) -> None:
        super().__init__("nao_autenticado", mensagem, 401, detalhe)


class NaoAutorizado(ErroAgroGuard):
    """Identidade autenticada, mas sem papel para a rota."""

    def __init__(self, mensagem: str = "Não autorizado.", detalhe: Any = None) -> None:
        super().__init__("nao_autorizado", mensagem, 403, detalhe)


class LimiteExcedido(ErroAgroGuard):
    """Rate limit por chave excedido."""

    def __init__(self, mensagem: str = "Limite de requisições excedido.", detalhe: Any = None) -> None:
        super().__init__("limite_excedido", mensagem, 429, detalhe)


class ModeloIndisponivel(ErroAgroGuard):
    """Modelo de ML não carregado — API não pode pontuar leituras."""

    def __init__(self, mensagem: str = "Modelo de risco indisponível.", detalhe: Any = None) -> None:
        super().__init__("modelo_indisponivel", mensagem, 503, detalhe)
