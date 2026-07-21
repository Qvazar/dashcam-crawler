from urllib.parse import urlsplit
import paramiko

class SftpTarget:
    @staticmethod
    def supports_url(url):
        return url.startswith("sftp://")

    def __init__(self, url):
        parts = urlsplit(url)
        self.user = parts.username
        self.password = parts.password
        self.host = parts.hostname
        self.path = parts.path
        self.port = parts.port if parts.port else 22  # Default SFTP port is 22

    def __enter__(self):
        self.ssh_client = paramiko.SshClient()
        self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh_client.connect(username=self.user, hostname=self.host, port=self.port, password=self.password)
        self.sftp = self.ssh_client.open_sftp()
        return self

    def put(self, file_path, destination_path):
        self.sftp.put(file_path, f"{self.path}/{destination_path}")

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.sftp.close()
        self.ssh_client.close()
    