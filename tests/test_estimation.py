import base64
from types import SimpleNamespace

import pytest

from myfitnesspal_mcp import estimation


@pytest.mark.parametrize("image", ["file:///secret", "https://localhost/x", "https://127.0.0.1/x",
                                  "sandbox:/photo", "data:image/jpeg;base64,???"])
def test_invalid_image_never_calls_api(image, monkeypatch):
    monkeypatch.setattr(estimation, "api_key", lambda: pytest.fail("Accessed key"))
    with pytest.raises(ValueError):
        estimation.estimate_food(image)


def test_measured_weight_and_no_logging(monkeypatch):
    result = dict(food_description="Chicken", preparation="cooked", mass_g=104,
                  lower_g=90, upper_g=120, kcal=150, protein_g=29.2, fat_g=3.7,
                  carbohydrate_g=0, identity_confidence="medium", assumptions=[], questions=[])
    import json

    def post(url, **kwargs):
        assert url == "https://api.openai.com/v1/responses"
        assert kwargs["json"]["store"] is False
        assert kwargs["follow_redirects"] is False
        return SimpleNamespace(status_code=200, json=lambda: {
            "status": "completed", "model": "test", "output": [{"content": [
                {"type": "output_text", "text": json.dumps(result)}]}]})

    monkeypatch.setattr(estimation, "api_key", lambda: "test")
    monkeypatch.setattr(estimation.httpx, "post", post)
    response = estimation.estimate_food(
        "data:image/jpeg;base64," + base64.b64encode(b"photo").decode(), measured_weight_g=104)
    assert response["estimate"]["lower_g"] == 104
    assert response["mass_basis"] == "measured"
    assert response["diary_changed"] is False


def test_attachment_discovery_file_contract():
    import asyncio

    from myfitnesspal_mcp.server import create_server
    tools = asyncio.run(create_server().list_tools())
    tool = next(t for t in tools if t.name == 'estimate_food_from_attachment')
    descriptor = tool.model_dump(by_alias=True)
    assert descriptor['_meta']['openai/fileParams'] == ['image', 'additional_images']
    schema = descriptor['inputSchema']
    image = schema['$defs']['ChatGPTImageFile']
    assert set(image['properties']) == {'download_url', 'file_id', 'mime_type', 'file_name'}
    assert set(image['required']) == {'download_url', 'file_id'}
    assert tool.annotations.readOnlyHint


def test_attachment_passes_download_url_without_exposing_reference(monkeypatch):
    received = []
    def estimate(url, context, mass, **kwargs):
        received.append((url, context, mass))
        return {'diary_changed': False, 'estimate': {'mass_g': mass}}
    monkeypatch.setattr(estimation, 'estimate_food', estimate)
    monkeypatch.setattr(estimation, 'download_attachment', lambda url: b'actual bytes')
    monkeypatch.setattr(estimation, 'attachment_data_url', lambda raw: 'data:image/jpeg;base64,bytes')
    image = estimation.ChatGPTImageFile(download_url='https://files.oaiusercontent.com/photo?signature=private', file_id='file-test')
    result = estimation.estimate_attachment(image, 'chicken', 104)
    assert received == [('data:image/jpeg;base64,bytes', 'chicken', 104)]
    assert 'private' not in str(result)
    assert result['diary_changed'] is False
    assert result['attachment_transport']['downloaded_bytes'] == 12


@pytest.mark.parametrize('url,mime', [('file-test',''), ('https://files.oaiusercontent.com/photo','application/pdf')])
def test_bad_attachment_never_calls_vision(url, mime, monkeypatch):
    monkeypatch.setattr(estimation, 'estimate_food', lambda *args: pytest.fail('Called inference'))
    image = estimation.ChatGPTImageFile(download_url=url,file_id='file-test',mime_type=mime)
    assert estimation.estimate_attachment(image)['error']


def test_download_redirect_and_no_credentials(monkeypatch):
    import httpx
    requests = []
    def respond(request):
        requests.append(request)
        assert 'authorization' not in request.headers
        if request.url.path == '/start':
            return httpx.Response(302, headers={'location': 'https://files.oaiusercontent.com/image'})
        return httpx.Response(200, content=b'image-bytes')
    original = httpx.Client
    monkeypatch.setattr(estimation.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    assert estimation.download_attachment('https://files.oaiusercontent.com/start') == b'image-bytes'
    assert len(requests) == 2


@pytest.mark.parametrize('location', ['http://files.oaiusercontent.com/x', 'https://127.0.0.1/x', 'https://files.oaiusercontent.com.evil.com/x'])
def test_download_blocks_redirect_outside_trusted_host(monkeypatch, location):
    import httpx
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(302, headers={'location': location})
    original = httpx.Client
    monkeypatch.setattr(estimation.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    with pytest.raises(estimation.AttachmentFailure):
        estimation.download_attachment('https://files.oaiusercontent.com/start')
    assert len(calls) == 1


@pytest.mark.parametrize('status,content_length', [(403,None), (200,'20000001')])
def test_failed_or_oversized_download_does_not_infer(monkeypatch,status,content_length):
    import httpx
    original = httpx.Client
    headers = {'content-length':content_length} if content_length else {}
    monkeypatch.setattr(estimation.httpx,'Client',lambda **kwargs: original(transport=httpx.MockTransport(lambda request:httpx.Response(status,headers=headers)),**kwargs))
    monkeypatch.setattr(estimation,'estimate_food',lambda *args: pytest.fail('Called inference'))
    image=estimation.ChatGPTImageFile(download_url='https://files.oaiusercontent.com/photo?secret=private',file_id='file-test')
    result=estimation.estimate_attachment(image)
    assert result['stage']=='attachment_download'
    assert 'private' not in str(result)
    assert result['diary_changed'] is False


def test_decoding_normalizes_real_image_and_rejects_html():
    import io

    from PIL import Image
    output=io.BytesIO()
    Image.new('RGB',(20,10),'white').save(output,format='PNG')
    data=estimation.attachment_data_url(output.getvalue())
    assert data.startswith('data:image/jpeg;base64,')
    with pytest.raises(estimation.AttachmentFailure):
        estimation.attachment_data_url(b'<html>Access denied</html>')


def test_api_error_code_does_not_leak_url(monkeypatch):
    import httpx
    monkeypatch.setattr(estimation,'api_key',lambda:'secret-key')
    monkeypatch.setattr(estimation.httpx,'post',lambda *a,**k:httpx.Response(400,headers={'x-request-id':'req_test'},json={'error':{'code':'invalid_image','param':'input[0].content[1].image_url','message':'secret signed URL'}}))
    result=estimation.estimate_food('data:image/jpeg;base64,YQ==')
    assert result['stage']=='image_inference'
    assert result['upstream_code']=='invalid_image'
    assert result['request_id']=='req_test'
    assert 'secret' not in str(result)


def test_reference_and_side_view_request_preserves_scope(monkeypatch):
    import httpx
    captured=[]
    monkeypatch.delenv('MFP_PORTION_PROTOCOL',raising=False)
    monkeypatch.delenv('MFP_ESTIMATION_MODEL',raising=False)
    monkeypatch.setattr(estimation,'api_key',lambda:'test')
    def post(url,**kwargs):
        captured.append(kwargs['json'])
        return httpx.Response(400,json={'error':{'code':'invalid_request_error'}})
    monkeypatch.setattr(estimation.httpx,'post',post)
    estimation.estimate_food('data:image/jpeg;base64,YQ==',food_focus='chicken',plate_diameter_cm=26,additional_image_urls=['data:image/jpeg;base64,Yg=='])
    request=captured[0]
    content=request['input'][0]['content']
    assert len([part for part in content if part['type']=='input_image'])==2
    assert 'Plate outer diameter is 26 cm' in content[0]['text']
    assert 'Only estimate edible chicken' in content[0]['text']
    assert 'SAME portion' in content[0]['text']
    assert request['model']=='gpt-4.1-mini-2025-04-14'


@pytest.mark.parametrize('diameter',[float('nan'),0,100,True])
def test_invalid_plate_measurement_never_accesses_key(diameter,monkeypatch):
    monkeypatch.setattr(estimation,'api_key',lambda:pytest.fail('Accessed key'))
    with pytest.raises(ValueError):
        estimation.estimate_food('data:image/jpeg;base64,YQ==',plate_diameter_cm=diameter)


def test_too_many_views_rejected_before_download(monkeypatch):
    monkeypatch.setattr(estimation,'download_attachment',lambda *a:pytest.fail('Downloaded'))
    image=estimation.ChatGPTImageFile(download_url='https://files.oaiusercontent.com/photo',file_id='file-test')
    with pytest.raises(ValueError):
        estimation.estimate_attachment(image,additional_images=[image,image,image])
