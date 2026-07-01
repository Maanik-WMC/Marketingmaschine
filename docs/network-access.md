# Network Access

The default deployment binds business tools to `127.0.0.1` on the NVIDIA host. This is intentional: the agent API, CRM, scheduler, and automation tools should not be exposed directly with database and queue services.

Use `deploy/docker-compose.network-access.yml` when LAN access is needed. It starts one nginx proxy and exposes only browser/API entry points:

| Tool | LAN URL pattern |
| --- | --- |
| Marketing agent API | `http://<host-ip>:18117` |
| n8n | `http://<host-ip>:15678` |
| Postiz | `http://<host-ip>:14007` |
| Twenty CRM | `http://<host-ip>:14019` |
| Mautic | `http://<host-ip>:14020` |
| ComfyUI | `http://<host-ip>:18188` |
| Grafana | `http://<host-ip>:13030` |

The proxy allows private network ranges only: `127.0.0.1`, `10.0.0.0/8`, `172.16.0.0/12`, and `192.168.0.0/16`.

n8n is proxied through `host.docker.internal:5678` because the host-published port is the reliable path for webhook traffic from the network-access container.

Start it on the NVIDIA host:

```bash
docker compose -f deploy/docker-compose.network-access.yml up -d
```

Keep these services behind VPN or LAN firewall. Do not expose them directly to the public internet without HTTPS, SSO/basic auth, platform credentials review, and rate limiting.
