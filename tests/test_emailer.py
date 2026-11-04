"""n8n authentication, acknowledgement and failure contract without sending mail."""
from unittest.mock import patch

import httpx
import pytest
from backend.emailer import send_email


@pytest.fixture
def n8n_env(monkeypatch):
    monkeypatch.setenv('EMAIL_PROVIDER', 'n8n')
    monkeypatch.setenv('N8N_EMAIL_WEBHOOK_URL', 'https://workflow.example/webhook/interview-email')
    monkeypatch.setenv('N8N_EMAIL_WEBHOOK_TOKEN', 'test-only-header-secret')
    monkeypatch.setenv('SMTP_FROM', 'recruiting@example.com')


def test_n8n_sends_private_payload_server_side(n8n_env):
    with patch('backend.emailer.httpx.Client') as factory:
        client = factory.return_value.__enter__.return_value
        client.post.return_value = httpx.Response(200, json={'status': 'sent'})
        send_email('candidate@example.com', 'Invitation', 'private link')
        factory.assert_called_once_with(timeout=20, follow_redirects=False)
        args, kwargs = client.post.call_args
        assert args == ('https://workflow.example/webhook/interview-email',)
        assert kwargs['headers'] == {'X-Interview-Token': 'test-only-header-secret'}
        assert kwargs['json'] == {'event': 'interview.email', 'from': 'recruiting@example.com',
                                  'to': 'candidate@example.com', 'subject': 'Invitation', 'text': 'private link'}


@pytest.mark.parametrize('code,payload', [(200, {'message': 'Workflow started'}), (202, {'status': 'sent'}),
                                        (401, {}), (500, {}), (302, {}), (200, [])])
def test_n8n_does_not_treat_early_or_failed_ack_as_sent(n8n_env, code, payload):
    with patch('backend.emailer.httpx.Client') as factory:
        client = factory.return_value.__enter__.return_value
        client.post.return_value = httpx.Response(code, json=payload)
        with pytest.raises(RuntimeError):
            send_email('candidate@example.com', 'Invitation', 'private link')
        assert client.post.call_count == 1


def test_n8n_timeout_is_not_retried_or_fallback(n8n_env):
    with patch('backend.emailer.httpx.Client') as factory, patch('backend.emailer.smtplib.SMTP') as smtp:
        client = factory.return_value.__enter__.return_value
        client.post.side_effect = httpx.ReadTimeout('test')
        with pytest.raises(RuntimeError):
            send_email('candidate@example.com', 'Invitation', 'private link')
        assert client.post.call_count == 1
        smtp.assert_not_called()


@pytest.mark.parametrize('url', ['http://workflow.example/webhook/mail', 'https://user:pass@workflow.example/mail', ''])
def test_invalid_n8n_configuration_does_not_send(n8n_env, monkeypatch, url):
    monkeypatch.setenv('N8N_EMAIL_WEBHOOK_URL', url)
    with patch('backend.emailer.httpx.Client') as client, pytest.raises(RuntimeError):
        send_email('candidate@example.com', 'Invitation', 'private link')
    client.assert_not_called()
