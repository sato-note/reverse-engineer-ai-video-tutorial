"""Lean Remotion project scaffold and shared toolchain manifest."""

from __future__ import annotations


REMOTION_VERSION = "4.0.489"
SHARED_PACKAGE = {
    "name": "tutorial-remotion-shared-toolchain",
    "version": "1.0.0",
    "private": True,
    "engines": {"node": ">=18.17.0", "npm": ">=9.0.0"},
    "dependencies": {
        "@remotion/cli": REMOTION_VERSION,
        "react": "19.1.1",
        "react-dom": "19.1.1",
        "remotion": REMOTION_VERSION,
        "zod": "4.3.6",
    },
    "devDependencies": {
        "@types/react": "19.1.10",
        "@types/react-dom": "19.1.7",
        "typescript": "5.9.2",
    },
}


SCAFFOLD_FILES = {
    ".gitignore": "node_modules/\nout/\n.remotion/\n",
    "package.json": """{
  "name": "tutorial-remotion-project",
  "version": "1.0.0",
  "private": true,
  "engines": {
    "node": ">=18.17.0",
    "npm": ">=9.0.0"
  },
  "scripts": {
    "studio": "remotion studio src/index.ts",
    "compositions": "remotion compositions src/index.ts",
    "preflight:timeline": "node scripts/remotion-render-gate.cjs render",
    "render:smoke": "remotion render src/index.ts FrameworkSmoke out/framework-smoke.mp4",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "@remotion/cli": "4.0.489",
    "react": "19.1.1",
    "react-dom": "19.1.1",
    "remotion": "4.0.489",
    "zod": "4.3.6"
  },
  "devDependencies": {
    "@types/react": "19.1.10",
    "@types/react-dom": "19.1.7",
    "typescript": "5.9.2"
  }
}
""",
    "remotion.config.ts": """import {Config} from '@remotion/cli/config';
import './scripts/remotion-render-gate.cjs';

Config.setOverwriteOutput(true);
Config.setVideoImageFormat('jpeg');
""",
    "scripts/remotion-render-gate.cjs": r"""const fs = require('node:fs');
const path = require('node:path');

const fail = (message) => {
  throw new Error(`REMOTION RENDER BLOCKED: ${message}`);
};

const escapeRegex = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

const validate = (project = process.cwd()) => {
  const manifestPath = path.join(project, 'studio-timeline.json');
  if (!fs.existsSync(manifestPath)) fail('studio-timeline.json missing');
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  const required = ['composition_id', 'composition_component', 'root_file', 'component_source_file'];
  for (const field of required) if (!manifest[field]) fail(`${field} missing`);
  const rootPath = path.join(project, manifest.root_file);
  const componentPath = path.join(project, manifest.component_source_file);
  if (!fs.existsSync(rootPath)) fail(`root source missing: ${manifest.root_file}`);
  if (!fs.existsSync(componentPath)) fail(`component source missing: ${manifest.component_source_file}`);
  const root = fs.readFileSync(rootPath, 'utf8');
  const component = fs.readFileSync(componentPath, 'utf8');
  const blocks = root.match(/<Composition\b[\s\S]*?\/>/gi) || [];
  const linked = blocks.some((block) =>
    new RegExp(`\\bid\\s*=\\s*['"]${escapeRegex(manifest.composition_id)}['"]`).test(block) &&
    new RegExp(`\\bcomponent\\s*=\\s*{\\s*${escapeRegex(manifest.composition_component)}\\s*}`).test(block)
  );
  if (!linked) fail('manifest composition does not match Root.tsx');
  if (!Array.isArray(manifest.tracks) || manifest.tracks.length < 2) fail('at least two timeline tracks required');
  for (const track of manifest.tracks) {
    if (!track.name) fail('unnamed timeline track');
    const named = new RegExp(
      `<(?:Sequence|Series\\.Sequence)\\b[^>]*\\bname\\s*=\\s*[{]?['"]${escapeRegex(track.name)}['"]`,
      'i'
    );
    if (!named.test(component)) fail(`named Sequence missing: ${track.name}`);
  }
  const verification = manifest.studio_verification || {};
  if (verification.status !== 'pass') fail('Studio verification not passed');
  if (!verification.screenshot_path || !fs.existsSync(path.join(project, verification.screenshot_path))) {
    fail('Studio timeline screenshot missing');
  }
  const visible = new Set(verification.visible_track_names || []);
  for (const track of manifest.tracks) if (!visible.has(track.name)) fail(`track not screenshot-verified: ${track.name}`);
};

const isRender = process.argv.some((arg) => arg === 'render');
const smokeBypass = process.env.REMOTION_ALLOW_UNVERIFIED_SMOKE === '1' && process.argv.includes('FrameworkSmoke');
if (isRender && !smokeBypass) validate();

module.exports = {validate};
""",
    "src/index.ts": """import {registerRoot} from 'remotion';
import {Root} from './Root';

registerRoot(Root);
""",
    "src/Root.tsx": """import {Composition} from 'remotion';
import {FrameworkSmoke, frameworkSmokeSchema} from './scenes/FrameworkSmoke';

export const Root = () => (
  <Composition
    id="FrameworkSmoke"
    component={FrameworkSmoke}
    durationInFrames={30}
    fps={30}
    width={1920}
    height={1080}
    schema={frameworkSmokeSchema}
    defaultProps={{
      label: 'REMOTION READY',
      accent: '#e04329',
      scale: 1,
      opacity: 1,
      rotate: 0,
    }}
  />
);
""",
    "src/scenes/FrameworkSmoke.tsx": """import {AbsoluteFill, interpolate, Sequence, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {z} from 'zod';

export const frameworkSmokeSchema = z.object({
  label: z.string(),
  accent: z.string(),
  scale: z.number(),
  opacity: z.number(),
  rotate: z.number(),
});

export const FrameworkSmoke = ({label, accent, scale, opacity, rotate}: z.infer<typeof frameworkSmokeSchema>) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const pop = spring({frame, fps, config: {damping: 16}});
  const stroke = interpolate(frame, [4, 24], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

  return (
    <AbsoluteFill style={{backgroundColor: '#f4eddc', alignItems: 'center', justifyContent: 'center'}}>
      <Sequence name="Title" from={0} durationInFrames={30} layout="none">
        <div style={{opacity, transform: `scale(${scale * pop}) rotate(${rotate}deg)`, font: '900 92px Arial'}}>
          {label}
        </div>
      </Sequence>
      <Sequence name="Accent stroke" from={4} durationInFrames={26} layout="none">
        <div style={{position: 'absolute', width: `${620 * stroke}px`, height: 18, backgroundColor: accent, top: 650}} />
      </Sequence>
    </AbsoluteFill>
  );
};
""",
    "studio-timeline.json": """{
  "schema_version": 1,
  "composition_id": "FrameworkSmoke",
  "composition_component": "FrameworkSmoke",
  "root_file": "src/Root.tsx",
  "component_source_file": "src/scenes/FrameworkSmoke.tsx",
  "source_files": ["src/Root.tsx", "src/scenes/FrameworkSmoke.tsx"],
  "elements": [
    {"id": "title", "role": "headline", "tweakable_props": ["label", "scale", "opacity", "rotate"]},
    {"id": "accent", "role": "accent", "tweakable_props": ["accent"]}
  ],
  "tracks": [
    {"name": "Title", "role": "headline", "element_ids": ["title"], "from": 0, "duration_in_frames": 30, "source_component": "FrameworkSmoke"},
    {"name": "Accent stroke", "role": "accent", "element_ids": ["accent"], "from": 4, "duration_in_frames": 26, "source_component": "FrameworkSmoke"}
  ],
  "studio_verification": {"status": "pending", "screenshot_path": "", "visible_track_names": []}
}
""",
    "tsconfig.json": """{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["DOM", "ES2022"],
    "jsx": "react-jsx",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "noEmit": true,
    "skipLibCheck": true
  },
  "include": ["src", "remotion.config.ts"]
}
""",
}
