#!/usr/bin/env node
import { spawn } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { isAbsolute, join, resolve } from "node:path";

const SIM_RESOURCE = "USB0::SIM::E36312A::INSTR";
const PLANNING_MODEL_ID = "keysight-e36312a";
const JOB_ID = "power-sim-read-status";
const DEFAULTS = {
  out: ".tmp_tests/power_sim_workflow",
  resource: SIM_RESOURCE,
  port: "18766",
  readyTimeoutMs: "3000",
  waitReadyTimeoutMs: "10000",
  jobTimeoutMs: "15000",
  stopTimeoutMs: "10000",
  clientTimeoutMs: "3000",
};

function usage() {
  return [
    "Usage: node run_power_sim_workflow.mjs [options]",
    "",
    "Runs one fixed, read-only E36312A simulator Worker workflow.",
    "Live mode, arbitrary resources, and output-affecting commands are not supported.",
    "",
    "Options:",
    "  --exe <path>                 powers-tool executable; default: one powers-tool*.exe in cwd",
    "  --out <dir>                  artifact directory; default: .tmp_tests/power_sim_workflow",
    `  --resource <string>          must be exactly ${SIM_RESOURCE}`,
    "  --port <number>              owned Worker control port; default: 18766",
    "  --ready-timeout-ms <n>       stdout ready wait before wait-ready fallback; default: 3000",
    "  --wait-ready-timeout-ms <n>  wait-ready deadline; default: 10000",
    "  --job-timeout-ms <n>         terminal result deadline; default: 15000",
    "  --stop-timeout-ms <n>        owned Worker exit deadline after stop; default: 10000",
    "  --client-timeout-ms <n>      CLI HTTP client timeout; default: 3000",
    "  -h, --help                   show this help",
  ].join("\n");
}

function parseArgs(argv) {
  const options = { ...DEFAULTS };
  const keyMap = {
    "--exe": "exe",
    "--out": "out",
    "--resource": "resource",
    "--port": "port",
    "--ready-timeout-ms": "readyTimeoutMs",
    "--wait-ready-timeout-ms": "waitReadyTimeoutMs",
    "--job-timeout-ms": "jobTimeoutMs",
    "--stop-timeout-ms": "stopTimeoutMs",
    "--client-timeout-ms": "clientTimeoutMs",
  };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--help" || argument === "-h") {
      console.log(usage());
      process.exit(0);
    }
    const key = keyMap[argument];
    if (!key) {
      throw new Error(`unknown argument: ${argument}\n${usage()}`);
    }
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) {
      throw new Error(`missing value for ${argument}`);
    }
    options[key] = value;
    index += 1;
  }
  return options;
}

function toAbsolute(path) {
  return isAbsolute(path) ? path : resolve(process.cwd(), path);
}

function positiveInteger(name, value) {
  if (!/^\d+$/.test(String(value))) {
    throw new Error(`${name} must be a positive integer`);
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1) {
    throw new Error(`${name} must be a positive integer`);
  }
  return parsed;
}

function deterministicResource(value) {
  if (value !== SIM_RESOURCE) {
    throw new Error(
      `--resource must be the deterministic no-hardware resource ${SIM_RESOURCE}; got ${value}`,
    );
  }
  return value;
}

function findExecutable(explicitExecutable) {
  if (explicitExecutable) {
    const executable = toAbsolute(explicitExecutable);
    if (!existsSync(executable)) {
      throw new Error(`executable not found: ${executable}`);
    }
    return executable;
  }
  const candidates = readdirSync(process.cwd())
    .filter((name) => /^powers-tool(?:-\d[^\\/]*)?\.exe$/i.test(name))
    .map((name) => join(process.cwd(), name));
  if (candidates.length === 1) {
    return candidates[0];
  }
  if (candidates.length === 0) {
    throw new Error("no powers-tool*.exe found in cwd; pass --exe");
  }
  throw new Error(`multiple powers-tool executables found; pass --exe: ${candidates.join(", ")}`);
}

function hasSchema2(value) {
  return (
    value !== null &&
    typeof value === "object" &&
    typeof value.schema_version === "number" &&
    Number.isInteger(value.schema_version) &&
    value.schema_version === 2
  );
}

function parseJson(text) {
  const trimmed = text.trim();
  if (!trimmed) {
    return { json: null, error: "empty stdout" };
  }
  try {
    const value = JSON.parse(trimmed);
    return {
      json: value,
      error: value !== null && typeof value === "object" && !Array.isArray(value)
        ? null
        : "stdout JSON must be an object",
    };
  } catch (error) {
    return { json: null, error: String(error?.message ?? error) };
  }
}

function readJsonFile(path) {
  if (!existsSync(path)) {
    return { json: null, error: `file not found: ${path}` };
  }
  const parsed = parseJson(readFileSync(path, "utf8"));
  return { ...parsed, path };
}

function writeJson(path, value) {
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function runCommand(executable, args, timeoutMs) {
  return new Promise((resolveCommand) => {
    const started = Date.now();
    const child = spawn(executable, args, {
      cwd: process.cwd(),
      windowsHide: true,
    });
    let stdout = "";
    let stderr = "";
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill();
    }, timeoutMs);
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      const parsed = parseJson(stdout);
      resolveCommand({
        args,
        exit_code: timedOut ? 3 : code,
        timed_out: timedOut,
        elapsed_ms: Date.now() - started,
        stdout,
        stderr,
        json: parsed.json,
        parse_error: parsed.error,
      });
    });
  });
}

function waitFor(predicate, timeoutMs) {
  return new Promise((resolveWait) => {
    const deadline = Date.now() + timeoutMs;
    const timer = setInterval(() => {
      const value = predicate();
      if (value) {
        clearInterval(timer);
        resolveWait(value);
      } else if (Date.now() >= deadline) {
        clearInterval(timer);
        resolveWait(null);
      }
    }, 50);
  });
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const executable = findExecutable(options.exe);
  const out = toAbsolute(options.out);
  const resource = deterministicResource(options.resource);
  const port = positiveInteger("--port", options.port);
  const readyTimeoutMs = positiveInteger("--ready-timeout-ms", options.readyTimeoutMs);
  const waitReadyTimeoutMs = positiveInteger(
    "--wait-ready-timeout-ms",
    options.waitReadyTimeoutMs,
  );
  const jobTimeoutMs = positiveInteger("--job-timeout-ms", options.jobTimeoutMs);
  const stopTimeoutMs = positiveInteger("--stop-timeout-ms", options.stopTimeoutMs);
  const clientTimeoutMs = positiveInteger("--client-timeout-ms", options.clientTimeoutMs);
  const commandTimeoutMs = Math.max(clientTimeoutMs + 5000, 10000);

  mkdirSync(out, { recursive: true });
  const paths = {
    stdout: join(out, "worker_stdout.jsonl"),
    stderr: join(out, "worker_stderr.txt"),
    waitReady: join(out, "wait_ready.json"),
    statusBefore: join(out, "status_before_command.json"),
    accepted: join(out, "accepted.json"),
    request: join(out, "request.json"),
    result: join(out, "result.json"),
    stop: join(out, "stop.json"),
    report: join(out, "power_sim_report.json"),
  };
  const workerArtifacts = join(out, `worker_runtime_${process.pid}_${Date.now()}`);
  const workerArgs = [
    "worker",
    "--mode",
    "simulate",
    "--resource",
    resource,
    "--control-port",
    String(port),
    "--artifacts-dir",
    workerArtifacts,
  ];
  const worker = spawn(executable, workerArgs, {
    cwd: process.cwd(),
    windowsHide: true,
  });
  worker.stdout.setEncoding("utf8");
  worker.stderr.setEncoding("utf8");

  let stdout = "";
  let stderr = "";
  let pendingLine = "";
  const events = [];
  const parseErrors = [];
  worker.stdout.on("data", (chunk) => {
    stdout += chunk;
    pendingLine += chunk;
    while (pendingLine.includes("\n")) {
      const newline = pendingLine.indexOf("\n");
      const line = pendingLine.slice(0, newline).trim();
      pendingLine = pendingLine.slice(newline + 1);
      if (!line) continue;
      try {
        const event = JSON.parse(line);
        if (event === null || typeof event !== "object" || Array.isArray(event)) {
          parseErrors.push({ line, message: "JSONL value must be an object" });
        } else {
          events.push(event);
        }
      } catch (error) {
        parseErrors.push({ line, message: String(error?.message ?? error) });
      }
    }
  });
  worker.stderr.on("data", (chunk) => {
    stderr += chunk;
  });
  const workerClosed = new Promise((resolveClosed) => {
    worker.on("close", (code) => resolveClosed(code));
  });

  const clients = {};
  let ready = await waitFor(
    () => events.find((event) => event.event === "ready") ?? null,
    readyTimeoutMs,
  );
  if (!ready && worker.exitCode === null) {
    clients.wait_ready_fallback = await runCommand(
      executable,
      [
        "wait-ready",
        "--port",
        String(port),
        "--json",
        "--timeout-ms",
        String(clientTimeoutMs),
        "--wait-timeout-ms",
        String(waitReadyTimeoutMs),
      ],
      waitReadyTimeoutMs + 5000,
    );
  }

  clients.wait_ready = await runCommand(
    executable,
    [
      "wait-ready",
      "--port",
      String(port),
      "--json",
      "--timeout-ms",
      String(clientTimeoutMs),
      "--wait-timeout-ms",
      String(waitReadyTimeoutMs),
    ],
    waitReadyTimeoutMs + 5000,
  );
  writeJson(paths.waitReady, clients.wait_ready.json ?? {
    parse_error: clients.wait_ready.parse_error,
    exit_code: clients.wait_ready.exit_code,
  });

  clients.status_before_command = await runCommand(
    executable,
    ["status", "--port", String(port), "--json", "--timeout-ms", String(clientTimeoutMs)],
    commandTimeoutMs,
  );
  writeJson(paths.statusBefore, clients.status_before_command.json ?? {
    parse_error: clients.status_before_command.parse_error,
    exit_code: clients.status_before_command.exit_code,
  });

  clients.send_command = await runCommand(
    executable,
    [
      "send-command",
      "--port",
      String(port),
      "--command",
      "read-status",
      "--arguments-json",
      '{"channel":"all"}',
      "--context-json",
      `{"mode":"simulate","planning_model_id":"${PLANNING_MODEL_ID}"}`,
      "--job-id",
      JOB_ID,
      "--json",
      "--timeout-ms",
      String(clientTimeoutMs),
    ],
    commandTimeoutMs,
  );
  writeJson(paths.accepted, clients.send_command.json ?? {
    parse_error: clients.send_command.parse_error,
    exit_code: clients.send_command.exit_code,
  });

  const accepted = clients.send_command.json;
  const artifactPath =
    accepted && typeof accepted.artifact_path === "string" ? accepted.artifact_path : null;
  const sourceRequestPath = artifactPath ? join(artifactPath, "request.json") : null;
  const sourceResultPath = artifactPath ? join(artifactPath, "result.json") : null;
  if (sourceRequestPath && existsSync(sourceRequestPath)) {
    copyFileSync(sourceRequestPath, paths.request);
  }

  let terminalStatus = null;
  let resultAvailable = sourceResultPath ? existsSync(sourceResultPath) : false;
  const jobDeadline = Date.now() + jobTimeoutMs;
  while (!resultAvailable && Date.now() < jobDeadline && worker.exitCode === null) {
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 100));
    resultAvailable = sourceResultPath ? existsSync(sourceResultPath) : false;
    if (!resultAvailable) {
      const status = await runCommand(
        executable,
        ["status", "--port", String(port), "--json", "--timeout-ms", String(clientTimeoutMs)],
        commandTimeoutMs,
      );
      if (status.exit_code === 0 && status.json) {
        terminalStatus = status.json;
      }
    }
  }
  if (sourceResultPath && existsSync(sourceResultPath)) {
    copyFileSync(sourceResultPath, paths.result);
  }
  const requestArtifact = readJsonFile(paths.request);
  const resultArtifact = readJsonFile(paths.result);

  clients.stop = await runCommand(
    executable,
    [
      "stop",
      "--port",
      String(port),
      "--reason",
      "power simulator smoke complete",
      "--json",
      "--timeout-ms",
      String(clientTimeoutMs),
    ],
    commandTimeoutMs,
  );
  writeJson(paths.stop, clients.stop.json ?? {
    parse_error: clients.stop.parse_error,
    exit_code: clients.stop.exit_code,
  });

  let workerExitCode = await Promise.race([
    workerClosed,
    new Promise((resolveTimeout) => setTimeout(() => resolveTimeout("timeout"), stopTimeoutMs)),
  ]);
  let forcedTermination = false;
  if (workerExitCode === "timeout") {
    forcedTermination = true;
    worker.kill();
    workerExitCode = await workerClosed;
  }
  if (pendingLine.trim()) {
    const line = pendingLine.trim();
    try {
      const event = JSON.parse(line);
      if (event === null || typeof event !== "object" || Array.isArray(event)) {
        parseErrors.push({ line, message: "JSONL value must be an object" });
      } else {
        events.push(event);
      }
    } catch (error) {
      parseErrors.push({ line, message: String(error?.message ?? error) });
    }
  }
  writeFileSync(paths.stdout, stdout, "utf8");
  writeFileSync(paths.stderr, stderr, "utf8");

  ready = events.find((event) => event.event === "ready") ?? ready;
  const summary = events.findLast((event) => event.event === "summary") ?? null;
  const relevantJobEvents = events.filter(
    (event) => event.job_id === JOB_ID || event.worker_job_id === accepted?.worker_job_id,
  );
  const runIds = {
    ready: ready?.run_id ?? null,
    wait_ready: clients.wait_ready.json?.run_id ?? null,
    status_before_command: clients.status_before_command.json?.run_id ?? null,
    terminal_status: terminalStatus?.run_id ?? null,
    result: resultArtifact.json?.run_id ?? null,
    summary: summary?.run_id ?? null,
  };
  const expectedRunId = runIds.ready;
  const presentRunIds = Object.values(runIds).filter((value) => value !== null);
  const workerJobId = accepted?.worker_job_id ?? null;
  const checks = {
    fixed_simulator_resource: resource === SIM_RESOURCE,
    worker_ready_observed: Boolean(ready),
    worker_events_present: events.length > 0,
    worker_events_schema_v2: events.length > 0 && events.every(hasSchema2),
    worker_jsonl_parse_ok: parseErrors.length === 0,
    wait_ready_ok:
      clients.wait_ready.exit_code === 0 &&
      clients.wait_ready.parse_error === null &&
      clients.wait_ready.json?.status === "ready",
    wait_ready_schema_v2: hasSchema2(clients.wait_ready.json),
    status_before_ok:
      clients.status_before_command.exit_code === 0 &&
      clients.status_before_command.parse_error === null &&
      clients.status_before_command.json?.ok === true,
    status_before_schema_v2: hasSchema2(clients.status_before_command.json),
    accepted_http_202:
      clients.send_command.exit_code === 0 &&
      clients.send_command.parse_error === null &&
      accepted?.http_status === 202 &&
      accepted?.status === "accepted",
    accepted_schema_v2: hasSchema2(accepted),
    accepted_command: accepted?.command === "read-status",
    accepted_job_id: accepted?.job_id === JOB_ID,
    accepted_worker_job_id: typeof workerJobId === "string" && workerJobId.length > 0,
    accepted_artifact_path: typeof artifactPath === "string" && artifactPath.length > 0,
    request_json_parse_ok: requestArtifact.error === null,
    request_json_schema_v2: hasSchema2(requestArtifact.json),
    request_json_command: requestArtifact.json?.command === "read-status",
    request_json_arguments:
      requestArtifact.json?.arguments?.channel === "all" &&
      requestArtifact.json?.arguments?.max_errors === 20 &&
      Object.keys(requestArtifact.json?.arguments ?? {}).length === 2,
    request_json_context:
      requestArtifact.json?.context?.mode === "simulate" &&
      requestArtifact.json?.context?.planning_model_id === PLANNING_MODEL_ID &&
      Object.keys(requestArtifact.json?.context ?? {}).length === 2,
    terminal_result_present: resultArtifact.error === null,
    result_json_schema_v2: hasSchema2(resultArtifact.json),
    result_succeeded:
      resultArtifact.json?.ok === true && resultArtifact.json?.status === "succeeded",
    result_command: resultArtifact.json?.command?.name === "read-status",
    result_worker_job_id: resultArtifact.json?.worker_job_id === workerJobId,
    run_id_correlated:
      typeof expectedRunId === "string" &&
      expectedRunId.length > 0 &&
      presentRunIds.length >= 5 &&
      presentRunIds.every((value) => value === expectedRunId),
    job_events_present: relevantJobEvents.length >= 3,
    job_event_job_id_correlated:
      relevantJobEvents.length > 0 &&
      relevantJobEvents.every((event) => event.job_id === JOB_ID),
    job_event_worker_job_id_correlated:
      relevantJobEvents.length > 0 &&
      relevantJobEvents.every((event) => event.worker_job_id === workerJobId),
    job_event_run_id_correlated:
      relevantJobEvents.filter((event) => Object.hasOwn(event, "run_id")).length >= 2 &&
      relevantJobEvents
        .filter((event) => Object.hasOwn(event, "run_id"))
        .every((event) => event.run_id === expectedRunId),
    stop_acknowledged:
      clients.stop.exit_code === 0 &&
      clients.stop.parse_error === null &&
      clients.stop.json?.ok === true &&
      typeof clients.stop.json?.message === "string" &&
      clients.stop.json.message.length > 0,
    final_summary_present: Boolean(summary),
    final_summary_ok: summary?.ok === true,
    no_forced_termination: forcedTermination === false,
    worker_exit_code_zero: workerExitCode === 0,
  };
  const ok = Object.values(checks).every(Boolean);
  const report = {
    schema_version: 1,
    runtime_schema_version: 2,
    ok,
    generated_at: new Date().toISOString(),
    executable,
    resource,
    planning_model_id: PLANNING_MODEL_ID,
    command: "read-status",
    job_id: JOB_ID,
    worker_job_id: workerJobId,
    run_id: expectedRunId,
    port,
    artifact_paths: paths,
    worker_artifacts: workerArtifacts,
    accepted_artifact_path: artifactPath,
    worker_args: [executable, ...workerArgs],
    clients,
    request: requestArtifact.json,
    request_parse_error: requestArtifact.error,
    result: resultArtifact.json,
    result_parse_error: resultArtifact.error,
    terminal_status: terminalStatus,
    events,
    event_sequence: events.map((event) => event.event),
    parse_errors: parseErrors,
    run_ids: runIds,
    summary,
    worker_exit_code: workerExitCode,
    forced_termination: forcedTermination,
    checks,
  };
  writeJson(paths.report, report);
  console.log(JSON.stringify(report, null, 2));
  return ok ? 0 : 3;
}

main()
  .then((code) => {
    process.exitCode = code;
  })
  .catch((error) => {
    console.error(error?.stack ?? String(error));
    process.exitCode = 3;
  });
