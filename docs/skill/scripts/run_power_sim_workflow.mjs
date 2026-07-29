#!/usr/bin/env node
import { spawn } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
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
    "  --ready-timeout-ms <n>       owned stdout ready deadline; default: 3000",
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
    let stdout = "";
    let stderr = "";
    let timedOut = false;
    let settled = false;
    let timer = null;
    let child = null;

    const finish = (code, spawnError = null) => {
      if (settled) return;
      settled = true;
      if (timer !== null) clearTimeout(timer);
      const parsed = parseJson(stdout);
      resolveCommand({
        args,
        exit_code: timedOut ? 3 : (Number.isInteger(code) ? code : 3),
        timed_out: timedOut,
        elapsed_ms: Date.now() - started,
        stdout,
        stderr,
        json: parsed.json,
        parse_error: parsed.error,
        spawn_error: spawnError ? String(spawnError?.message ?? spawnError) : null,
      });
    };

    try {
      child = spawn(executable, args, {
        cwd: process.cwd(),
        windowsHide: true,
      });
    } catch (error) {
      finish(3, error);
      return;
    }
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.once("error", (error) => {
      stderr += `${String(error?.stack ?? error)}\n`;
      finish(3, error);
    });
    child.on("close", (code) => {
      finish(code);
    });
    timer = setTimeout(() => {
      timedOut = true;
      try {
        child.kill();
      } catch (error) {
        finish(3, error);
      }
    }, timeoutMs);
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
  for (const path of Object.values(paths)) {
    rmSync(path, { force: true });
  }
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
  let worker = null;
  let workerClosed = Promise.resolve(null);
  let workerExited = false;
  let workerExitCode = null;
  let workerSpawnError = null;
  let stdout = "";
  let stderr = "";
  let pendingLine = "";
  const events = [];
  const parseErrors = [];
  const clients = {};
  const artifactWriteErrors = [];
  const cleanupErrors = [];
  let ready = null;
  let ownedRunId = null;
  let portIdentityConfirmed = false;
  let portIdentityMismatch = false;
  let cooperativeStopAttempted = false;
  let cooperativeStopSucceeded = false;
  let forcedTermination = false;
  let workflowError = null;
  let accepted = null;
  let acceptedEvent = null;
  let artifactPath = null;
  let requestArtifact = { json: null, error: "request artifact not read" };
  let resultArtifact = { json: null, error: "result artifact not read" };
  let statusAfterResult = null;

  const parseWorkerLine = (rawLine) => {
    const line = rawLine.trim();
    if (!line) return;
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
  };
  const ownedStatus = (client) =>
    client?.exit_code === 0 &&
    client?.parse_error === null &&
    client?.spawn_error === null &&
    hasSchema2(client?.json) &&
    client.json.run_id === ownedRunId;
  const recordIdentityMismatch = (client) => {
    if (
      hasSchema2(client?.json) &&
      typeof client.json.run_id === "string" &&
      client.json.run_id &&
      client.json.run_id !== ownedRunId
    ) {
      portIdentityMismatch = true;
      portIdentityConfirmed = false;
    }
  };

  try {
    worker = spawn(executable, workerArgs, {
      cwd: process.cwd(),
      windowsHide: true,
    });
    worker.stdout.setEncoding("utf8");
    worker.stderr.setEncoding("utf8");
    worker.stdout.on("data", (chunk) => {
      stdout += chunk;
      pendingLine += chunk;
      while (pendingLine.includes("\n")) {
        const newline = pendingLine.indexOf("\n");
        parseWorkerLine(pendingLine.slice(0, newline));
        pendingLine = pendingLine.slice(newline + 1);
      }
    });
    worker.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    worker.once("error", (error) => {
      workerSpawnError = String(error?.message ?? error);
      stderr += `${String(error?.stack ?? error)}\n`;
    });
    workerClosed = new Promise((resolveClosed) => {
      worker.once("close", (code) => {
        workerExited = true;
        workerExitCode = Number.isInteger(code) ? code : 3;
        resolveClosed(workerExitCode);
      });
    });

    ready = await waitFor(() => {
      const validReady = events.find(
        (event) =>
          hasSchema2(event) &&
          event.event === "ready" &&
          typeof event.run_id === "string" &&
          event.run_id.length > 0,
      );
      if (validReady) return validReady;
      if (workerSpawnError || workerExited) return { startup_failed: true };
      return null;
    }, readyTimeoutMs);
    if (!ready || ready.startup_failed) {
      throw new Error(
        workerSpawnError
          ? `Worker subprocess failed to start: ${workerSpawnError}`
          : "owned Worker did not emit a valid schema-2 ready event",
      );
    }
    ownedRunId = ready.run_id;

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
      spawn_error: clients.wait_ready.spawn_error,
      exit_code: clients.wait_ready.exit_code,
    });
    recordIdentityMismatch(clients.wait_ready);
    if (!ownedStatus(clients.wait_ready)) {
      throw new Error("wait-ready did not confirm the owned Worker run_id");
    }
    portIdentityConfirmed = true;
    if (parseErrors.length > 0) {
      throw new Error("Worker stdout contained a JSONL parse error");
    }

    clients.status_before_command = await runCommand(
      executable,
      ["status", "--port", String(port), "--json", "--timeout-ms", String(clientTimeoutMs)],
      commandTimeoutMs,
    );
    writeJson(paths.statusBefore, clients.status_before_command.json ?? {
      parse_error: clients.status_before_command.parse_error,
      spawn_error: clients.status_before_command.spawn_error,
      exit_code: clients.status_before_command.exit_code,
    });
    recordIdentityMismatch(clients.status_before_command);
    if (!ownedStatus(clients.status_before_command)) {
      throw new Error("status did not confirm the owned Worker run_id");
    }

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
      spawn_error: clients.send_command.spawn_error,
      exit_code: clients.send_command.exit_code,
    });
    accepted = clients.send_command.json;
    if (
      clients.send_command.exit_code !== 0 ||
      clients.send_command.parse_error !== null ||
      clients.send_command.spawn_error !== null ||
      !hasSchema2(accepted) ||
      accepted?.http_status !== 202 ||
      accepted?.status !== "accepted" ||
      accepted?.command !== "read-status" ||
      accepted?.job_id !== JOB_ID ||
      typeof accepted?.worker_job_id !== "string" ||
      !accepted.worker_job_id ||
      typeof accepted?.artifact_path !== "string" ||
      !accepted.artifact_path
    ) {
      throw new Error("send-command did not return the expected accepted response");
    }
    artifactPath = accepted.artifact_path;

    acceptedEvent = await waitFor(
      () =>
        events.find(
          (event) =>
            event.event === "job_accepted" &&
            event.job_id === JOB_ID &&
            event.worker_job_id === accepted.worker_job_id,
        ) ?? null,
      clientTimeoutMs,
    );
    if (!acceptedEvent || !hasSchema2(acceptedEvent) || acceptedEvent.run_id !== ownedRunId) {
      throw new Error("job_accepted event did not correlate to the owned Worker");
    }

    clients.status_after_acceptance = await runCommand(
      executable,
      ["status", "--port", String(port), "--json", "--timeout-ms", String(clientTimeoutMs)],
      commandTimeoutMs,
    );
    recordIdentityMismatch(clients.status_after_acceptance);
    if (!ownedStatus(clients.status_after_acceptance)) {
      throw new Error("post-acceptance status did not confirm the owned Worker run_id");
    }

    const sourceRequestPath = join(artifactPath, "request.json");
    const sourceResultPath = join(artifactPath, "result.json");
    if (!existsSync(sourceRequestPath)) {
      throw new Error(`request artifact not found: ${sourceRequestPath}`);
    }
    copyFileSync(sourceRequestPath, paths.request);
    requestArtifact = readJsonFile(paths.request);
    if (requestArtifact.error !== null || !hasSchema2(requestArtifact.json)) {
      throw new Error(requestArtifact.error ?? "request artifact did not use schema 2");
    }

    const resultAvailable = await waitFor(
      () => existsSync(sourceResultPath) || workerExited,
      jobTimeoutMs,
    );
    if (!resultAvailable || !existsSync(sourceResultPath)) {
      throw new Error("accepted job did not produce terminal result.json");
    }
    copyFileSync(sourceResultPath, paths.result);
    resultArtifact = readJsonFile(paths.result);
    if (
      resultArtifact.error !== null ||
      !hasSchema2(resultArtifact.json) ||
      resultArtifact.json?.run_id !== ownedRunId ||
      resultArtifact.json?.worker_job_id !== accepted.worker_job_id ||
      resultArtifact.json?.status !== "succeeded" ||
      resultArtifact.json?.ok !== true
    ) {
      throw new Error("terminal result did not correlate or succeed");
    }

    clients.status_after_result = await runCommand(
      executable,
      ["status", "--port", String(port), "--json", "--timeout-ms", String(clientTimeoutMs)],
      commandTimeoutMs,
    );
    statusAfterResult = clients.status_after_result.json;
    recordIdentityMismatch(clients.status_after_result);
    if (!ownedStatus(clients.status_after_result)) {
      throw new Error("post-result status did not confirm the owned Worker run_id");
    }
  } catch (error) {
    workflowError = String(error?.message ?? error);
  } finally {
    if (worker && !workerExited && ownedRunId && !portIdentityMismatch) {
      clients.status_before_stop = await runCommand(
        executable,
        ["status", "--port", String(port), "--json", "--timeout-ms", String(clientTimeoutMs)],
        commandTimeoutMs,
      );
      recordIdentityMismatch(clients.status_before_stop);
      if (ownedStatus(clients.status_before_stop)) {
        portIdentityConfirmed = true;
        cooperativeStopAttempted = true;
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
        cooperativeStopSucceeded =
          clients.stop.exit_code === 0 &&
          clients.stop.parse_error === null &&
          clients.stop.spawn_error === null &&
          clients.stop.json?.ok === true &&
          typeof clients.stop.json?.message === "string" &&
          clients.stop.json.message.length > 0;
        try {
          writeJson(paths.stop, clients.stop.json ?? {
            parse_error: clients.stop.parse_error,
            spawn_error: clients.stop.spawn_error,
            exit_code: clients.stop.exit_code,
          });
        } catch (error) {
          artifactWriteErrors.push(`stop.json: ${String(error?.message ?? error)}`);
        }
      } else {
        portIdentityConfirmed = false;
      }
    }

    if (worker && !workerExited) {
      const closeResult = await Promise.race([
        workerClosed,
        new Promise((resolveTimeout) =>
          setTimeout(() => resolveTimeout("timeout"), stopTimeoutMs),
        ),
      ]);
      if (closeResult === "timeout") {
        forcedTermination = true;
        try {
          worker.kill();
        } catch (error) {
          cleanupErrors.push(`worker termination: ${String(error?.message ?? error)}`);
        }
        const forcedCloseResult = await Promise.race([
          workerClosed,
          new Promise((resolveTimeout) =>
            setTimeout(() => resolveTimeout("timeout"), stopTimeoutMs),
          ),
        ]);
        if (forcedCloseResult === "timeout") {
          workerExitCode = null;
        }
      }
    }
    if (pendingLine.trim()) {
      parseWorkerLine(pendingLine);
      pendingLine = "";
    }
    try {
      writeFileSync(paths.stdout, stdout, "utf8");
    } catch (error) {
      artifactWriteErrors.push(`worker_stdout.jsonl: ${String(error?.message ?? error)}`);
    }
    try {
      writeFileSync(paths.stderr, stderr, "utf8");
    } catch (error) {
      artifactWriteErrors.push(`worker_stderr.txt: ${String(error?.message ?? error)}`);
    }
  }

  const summary = events.findLast((event) => event.event === "summary") ?? null;
  const relevantJobEvents = events.filter(
    (event) => event.job_id === JOB_ID || event.worker_job_id === accepted?.worker_job_id,
  );
  const runIds = {
    ready: ready?.run_id ?? null,
    wait_ready: clients.wait_ready?.json?.run_id ?? null,
    status_before_command: clients.status_before_command?.json?.run_id ?? null,
    accepted_event: acceptedEvent?.run_id ?? null,
    status_after_acceptance: clients.status_after_acceptance?.json?.run_id ?? null,
    status_after_result: statusAfterResult?.run_id ?? null,
    status_before_stop: clients.status_before_stop?.json?.run_id ?? null,
    result: resultArtifact.json?.run_id ?? null,
    summary: summary?.run_id ?? null,
  };
  const expectedRunId = ownedRunId;
  const presentRunIds = Object.values(runIds).filter((value) => value !== null);
  const workerJobId = accepted?.worker_job_id ?? null;
  const checks = {
    fixed_simulator_resource: resource === SIM_RESOURCE,
    workflow_no_error: workflowError === null,
    worker_ready_observed: Boolean(ready && !ready.startup_failed),
    ownership_ready_valid:
      hasSchema2(ready) &&
      ready?.event === "ready" &&
      typeof ownedRunId === "string" &&
      ownedRunId.length > 0,
    port_identity_confirmed: portIdentityConfirmed,
    port_identity_not_mismatched: portIdentityMismatch === false,
    worker_events_present: events.length > 0,
    worker_events_schema_v2: events.length > 0 && events.every(hasSchema2),
    worker_jsonl_parse_ok: parseErrors.length === 0,
    wait_ready_ok:
      clients.wait_ready?.exit_code === 0 &&
      clients.wait_ready?.parse_error === null &&
      clients.wait_ready?.spawn_error === null &&
      clients.wait_ready?.json?.status === "ready" &&
      clients.wait_ready?.json?.run_id === ownedRunId,
    wait_ready_schema_v2: hasSchema2(clients.wait_ready?.json),
    status_before_ok:
      clients.status_before_command?.exit_code === 0 &&
      clients.status_before_command?.parse_error === null &&
      clients.status_before_command?.spawn_error === null &&
      clients.status_before_command?.json?.ok === true &&
      clients.status_before_command?.json?.run_id === ownedRunId,
    status_before_schema_v2: hasSchema2(clients.status_before_command?.json),
    accepted_http_202:
      clients.send_command?.exit_code === 0 &&
      clients.send_command?.parse_error === null &&
      clients.send_command?.spawn_error === null &&
      accepted?.http_status === 202 &&
      accepted?.status === "accepted",
    accepted_schema_v2: hasSchema2(accepted),
    accepted_command: accepted?.command === "read-status",
    accepted_job_id: accepted?.job_id === JOB_ID,
    accepted_session_run_id_correlated: acceptedEvent?.run_id === ownedRunId,
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
      presentRunIds.length >= 7 &&
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
    cooperative_stop_attempted: cooperativeStopAttempted,
    stop_acknowledged: cooperativeStopSucceeded,
    final_summary_present: Boolean(summary),
    final_summary_ok: summary?.ok === true && summary?.run_id === ownedRunId,
    artifact_writes_ok: artifactWriteErrors.length === 0,
    cleanup_errors_absent: cleanupErrors.length === 0,
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
    owned_run_id: ownedRunId,
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
    terminal_status: statusAfterResult,
    events,
    event_sequence: events.map((event) => event.event),
    parse_errors: parseErrors,
    run_ids: runIds,
    summary,
    error: workflowError,
    ownership: {
      owned_run_id: ownedRunId,
      ready_observed: Boolean(ready && !ready.startup_failed),
      port_identity_confirmed: portIdentityConfirmed,
      port_identity_mismatch: portIdentityMismatch,
    },
    cleanup: {
      cooperative_stop_attempted: cooperativeStopAttempted,
      cooperative_stop_succeeded: cooperativeStopSucceeded,
      forced_termination: forcedTermination,
    },
    worker_spawn_error: workerSpawnError,
    worker_exit_code: workerExitCode,
    forced_termination: forcedTermination,
    artifact_write_errors: artifactWriteErrors,
    cleanup_errors: cleanupErrors,
    checks,
  };
  try {
    writeJson(paths.report, report);
  } catch (error) {
    console.error(`Could not write failure report: ${String(error?.message ?? error)}`);
    return 3;
  }
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
