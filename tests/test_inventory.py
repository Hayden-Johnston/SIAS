import importlib.util
from pathlib import Path
from urllib.error import URLError

spec = importlib.util.spec_from_file_location("inventory", Path(__file__).parents[1] / "ops/inventory.py")
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


def test_gpu_parser():
    assert inventory.parse_gpus('''{"card0": {"VRAM Total Memory (B)": "100",
        "VRAM Total Used Memory (B)": "25"}}''') == [
        {"index": 0, "vram_total_bytes": 100, "vram_used_bytes": 25}]


def test_df_parser():
    rows = inventory.parse_df("Filesystem 1-blocks Used Available Capacity Mounted on\n"
                              "/dev/test 1000 950 50 95% /mnt/model storage\n")
    assert rows[0] == {"device": "/dev/test", "total_bytes": 1000, "used_bytes": 950,
                           "free_bytes": 50, "used_percent": 95, "mount": "/mnt/model storage"}


def test_ss_parser():
    rows = inventory.parse_ss('LISTEN 0 128 [::]:8081 [::]:* users:(("llama-server",pid=1,fd=2))\n'
                              'LISTEN 0 128 0.0.0.0:8099 0.0.0.0:*\n')
    assert rows[0]['host'] == '::'
    assert rows[0]['port'] == 8081
    assert 'llama-server' in rows[0]['process']
    assert rows[1]['process'] is None


def test_docker_parser_omits_unneeded_fields():
    assert inventory.parse_docker('{"Names":"test", "Image":"llama", "Status":"Up",'
                                  '"Ports":"8081->8080/tcp", "Command":"secret"}\n') == [
        {"names": "test", "image": "llama", "status": "Up", "ports": "8081->8080/tcp"}]
    assert inventory.parse_docker('') == []


def test_ini_inherits_wildcard_and_preserves_unknowns():
    rows = inventory.parse_config('''[*]
device = ROCm0,ROCm1
ctx-size = 65536
[small]
model = /models/Test-Q4_K_M.gguf
[large]
model = /models/Test-BF16.gguf
ctx-size = 8192
port = 8081
''')
    assert rows[0] == {"name": "small", "model": "Test-Q4_K_M.gguf", "quant": "Q4_K_M",
                           "ctx": 65536, "gpus": "ROCm0,ROCm1", "port": None}
    assert rows[1]['quant'] == 'BF16'
    assert rows[1]['ctx'] == 8192
    assert rows[1]['port'] == 8081


def test_maya_skip_and_down(monkeypatch):
    monkeypatch.delenv('MAYA_API_KEY', raising=False)
    assert inventory.maya_status()['status'] == 'skipped'
    monkeypatch.setenv('MAYA_API_KEY', 'fixture-key')

    def fail(request, timeout):
        assert request.get_header('Authorization') == 'Bearer fixture-key'
        assert timeout == 3
        raise URLError('down')

    monkeypatch.setattr(inventory, 'urlopen', fail)
    assert inventory.maya_status() == {'status': 'down'}


def test_disk_metadata_and_hf_deduplication(tmp_path):
    root = tmp_path / 'huggingface'
    model = root / 'hub/models--example--test'
    (model / 'blobs').mkdir(parents=True)
    (model / 'snapshots').mkdir()
    blob = model / 'blobs/weight'
    blob.write_bytes(b'12345')
    (model / 'snapshots/weight').symlink_to(blob)
    errors = []
    assert inventory.disk_models(root, float('inf'), errors) == [
        {'name': 'hub/models--example--test', 'size_bytes': 5}]
    assert not errors
    gguf = tmp_path / 'gguf'
    gguf.mkdir()
    (gguf / 'test.gguf').write_bytes(b'123')
    (gguf / 'ignore.txt').write_text('ignored')
    assert inventory.disk_models(gguf, float('inf'), errors) == [
        {'name': 'test.gguf', 'size_bytes': 3}]
    assert inventory.disk_models(gguf, 0, errors) == []
    assert errors[-1]['error'] == 'scan_deadline'


def test_missing_commands_and_down_servers(monkeypatch):
    def fail(command, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(inventory.subprocess, 'run', fail)
    errors = []
    assert inventory.run(['ss'], errors) is None
    assert errors == [{'source': 'ss', 'error': 'FileNotFoundError'}]
    monkeypatch.setattr(inventory, 'run', lambda command, errors: '{}'
                        if command[0] == 'rocm-smi' else '')
    monkeypatch.setattr(inventory, 'maya_status', lambda: {'status': 'down'})
    monkeypatch.setattr(inventory, 'disk_models', lambda *args: [])
    monkeypatch.setattr(inventory.Path, 'glob', lambda *args: [])
    result = inventory.collect()
    assert all(server['status'] == 'down' for server in result['servers'])
