import { defineConfig, loadEnv, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

function readBody(stream: NodeJS.ReadableStream): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];

    stream.on("data", (chunk) => {
      chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
    });

    stream.on("end", () => {
      resolve(Buffer.concat(chunks));
    });

    stream.on("error", (error) => {
      reject(error);
    });
  });
}

function createDynamicApiProxy(defaultTarget: string): Plugin {
  return {
    name: "atm-dynamic-api-proxy",
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const requestUrl = req.url;
        if (!requestUrl || (!requestUrl.startsWith("/api/") && requestUrl !== "/api")) {
          next();
          return;
        }

        const dynamicHeader = req.headers["x-atm-target"];
        const dynamicTarget = Array.isArray(dynamicHeader) ? dynamicHeader[0] : dynamicHeader;
        const selectedTarget = dynamicTarget && dynamicTarget.startsWith("http") ? dynamicTarget : defaultTarget;

        try {
          const target = new URL(selectedTarget);
          const targetBasePath = target.pathname === "/" ? "" : target.pathname.replace(/\/$/, "");
          const upstreamPath = requestUrl.replace(/^\/api/, "") || "/";
          const upstreamUrl = new URL(`${target.origin}${targetBasePath}${upstreamPath}`);

          const headers = new Headers();
          Object.entries(req.headers).forEach(([key, value]) => {
            if (value === undefined) {
              return;
            }
            headers.set(key, Array.isArray(value) ? value.join(",") : value);
          });
          headers.delete("x-atm-target");
          headers.set("host", target.host);

          const method = req.method ?? "GET";
          const body = method === "GET" || method === "HEAD" ? undefined : await readBody(req);

          const upstreamResponse = await fetch(upstreamUrl, {
            method,
            headers,
            body,
            redirect: "manual",
          });

          res.statusCode = upstreamResponse.status;
          upstreamResponse.headers.forEach((value, key) => {
            if (key.toLowerCase() === "transfer-encoding") {
              return;
            }
            res.setHeader(key, value);
          });

          const responseBuffer = Buffer.from(await upstreamResponse.arrayBuffer());
          res.end(responseBuffer);
        } catch (error) {
          res.statusCode = 502;
          res.setHeader("content-type", "text/plain; charset=utf-8");
          const message = error instanceof Error ? error.message : String(error);
          res.end(`Proxy error: ${message}`);
        }
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backendTarget = env.ATM_BACKEND_TARGET || "http://127.0.0.1:8080";

  return {
    plugins: [react(), createDynamicApiProxy(backendTarget)],
    server: {
      port: 5173,
    },
  };
});
