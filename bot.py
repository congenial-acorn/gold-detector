import os


async def _dispatcher_loop():
await client.wait_until_ready()
while True:
msg = await queue.get()
try:
tasks = [asyncio.create_task(_send_to_guild(g, msg)) for g in client.guilds]
if tasks:
await asyncio.gather(*tasks, return_exceptions=True)
finally:
queue.task_done()


# ---- gold.py auto-run detection --------------------------------------------


def _find_noarg_entrypoint(mod) -> Optional[str]:
candidates = [
"start", "run", "main", "monitor", "watch", "loop", "monitor_metals"
]
for name in candidates:
fn = getattr(mod, name, None)
if callable(fn):
try:
sig = inspect.signature(fn)
# Check for required positional params (no default)
required = [p for p in sig.parameters.values()
if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
and p.default is p.empty]
if not required:
return name
except (TypeError, ValueError):
# Builtins or C funcs might not be introspectable; try anyway
return name
return None


@client.event
async def on_ready():
log(f"✅ Logged in as {client.user} (id={client.user.id})")


# Wire gold.py -> queue
if hasattr(gold, "set_emitter"):
gold.set_emitter(lambda m: queue.put_nowait(m))
log("Emitter registered via gold.set_emitter(...)")
else:
# Fallback: monkey-patch send_to_discord if present (same-process only)
if hasattr(gold, "send_to_discord") and callable(getattr(gold, "send_to_discord")):
setattr(gold, "send_to_discord", lambda m: queue.put_nowait(m))
log("Emitter installed by monkey-patching gold.send_to_discord(...)")
else:
log("WARNING: gold.py lacks set_emitter()/send_to_discord(); add the shim from Section 3.")


# Optionally auto-run gold forever with a no-arg entrypoint
if START_GOLD:
entry = _find_noarg_entrypoint(gold)
if entry:
def _run_gold():
try:
getattr(gold, entry)()
except Exception as e:
log(f"[gold.py:{entry}] exited with error: {e}")
threading.Thread(target=_run_gold, name=f"gold:{entry}", daemon=True).start()
log(f"Started gold.py entrypoint '{entry}' in background thread.")
else:
log("No no-arg entrypoint found in gold.py; run it separately or add a no-arg wrapper.")


# Start dispatcher
asyncio.create_task(_dispatcher_loop())


if __name__ == "__main__":
if not TOKEN:
raise SystemExit("Missing DISCORD_TOKEN in .env")
client.run(TOKEN)
