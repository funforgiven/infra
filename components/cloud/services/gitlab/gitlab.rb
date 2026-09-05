# Stateful backend for the GitLab Helm deployment. No Rails/web/registry here.
require 'json'
require 'digest'
credentials = JSON.parse(File.read('/run/gitlab-bootstrap/credentials.json'))
roles(['postgres_role'])
letsencrypt['enable'] = false
prometheus_monitoring['enable'] = false
# Keep database-object provisioning enabled; the postgres role disables Rails
# application services. Cache maintenance belongs to the Helm application.
gitlab_rails['rake_cache_clear'] = false
gitlab_rails['auto_migrate'] = false
gitlab_rails['internal_api_url'] = 'https://gitlab.fahrican.com'
gitlab_rails['redis_password'] = credentials.fetch('redis_password')
gitlab_shell['secret_token'] = credentials.fetch('shell_token')

# Authenticate even on the isolated tenant network. Never use trust for peers.
postgresql['enable'] = true
postgresql['listen_address'] = '0.0.0.0'
postgresql['sql_user'] = 'gitlab'
# The package prepends "md5" itself; this option expects only the hex digest.
postgresql['sql_user_password'] = Digest::MD5.hexdigest(credentials.fetch('postgres_password') + 'gitlab')
postgresql['md5_auth_cidr_addresses'] = ['192.168.82.0/24']
# The package's local readiness probe uses loopback during initial database setup.
postgresql['trust_auth_cidr_addresses'] = ['127.0.0.1/32', '::1/128']
postgresql['shared_buffers'] = '512MB'
postgresql['max_connections'] = 150

redis['enable'] = true
redis['bind'] = '0.0.0.0'
redis['port'] = 6379
redis['password'] = credentials.fetch('redis_password')
redis['maxmemory_policy'] = 'noeviction'
redis['appendonly'] = 'yes'

gitaly['enable'] = true
gitaly['gitlab_secret'] = credentials.fetch('shell_token')
gitaly['configuration'] = {
  listen_addr: '0.0.0.0:8075',
  auth: { token: credentials.fetch('gitaly_token') },
  storage: [{ name: 'default', path: '/var/opt/gitlab/git-data/repositories' }]
}
