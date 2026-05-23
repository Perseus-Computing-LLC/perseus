const vscode = require('vscode');
const { exec, spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

/** @type {vscode.StatusBarItem} */
let statusBar;
let watcher;
let outputChannel;

const OUTPUT_FILES = {
    claude: 'CLAUDE.md',
    cursor: '.cursorrules',
    codex: 'AGENTS.md',
    hermes: '.hermes.md',
    copilot: '.github/copilot-instructions.md'
};

function activate(context) {
    outputChannel = vscode.window.createOutputChannel('Perseus');
    outputChannel.appendLine('Perseus context engine activated');

    // Status bar
    statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    statusBar.command = 'perseus.render';
    context.subscriptions.push(statusBar);

    // Commands
    context.subscriptions.push(
        vscode.commands.registerCommand('perseus.render', renderNow),
        vscode.commands.registerCommand('perseus.init', initWorkspace),
        vscode.commands.registerCommand('perseus.watch', startWatching)
    );

    // Auto-start
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri?.fsPath;
    if (workspaceRoot && fs.existsSync(path.join(workspaceRoot, '.perseus', 'context.md'))) {
        const config = vscode.workspace.getConfiguration('perseus');
        if (config.get('autoRender')) {
            renderContext(workspaceRoot).then(() => startWatching());
        }
        updateStatusBar(true);
    } else {
        statusBar.text = '$(mirror) Perseus: not initialized';
        statusBar.show();
    }
}

async function renderNow() {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri?.fsPath;
    if (!root) {
        vscode.window.showErrorMessage('Perseus: no workspace open');
        return;
    }
    await renderContext(root);
}

async function initWorkspace() {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri?.fsPath;
    if (!root) return;

    const perseusBin = await findPerseus();
    if (!perseusBin) {
        vscode.window.showErrorMessage('Perseus not found. Install: pip install perseus-ctx');
        return;
    }

    return new Promise((resolve) => {
        exec(`"${perseusBin}" init "${root}"`, (err, stdout, stderr) => {
            if (err) {
                outputChannel.appendLine(`Init error: ${stderr}`);
                vscode.window.showErrorMessage(`Perseus init failed: ${stderr}`);
            } else {
                outputChannel.appendLine(stdout);
                vscode.window.showInformationMessage('Perseus workspace initialized. Edit .perseus/context.md to customize.');
                renderContext(root).then(() => startWatching());
            }
            resolve();
        });
    });
}

function startWatching() {
    const root = vscode.workspace.workspaceFolders?.[0]?.uri?.fsPath;
    if (!root) return;

    if (watcher) { watcher.dispose(); }

    const contextFile = path.join(root, '.perseus', 'context.md');
    if (!fs.existsSync(contextFile)) return;

    const config = vscode.workspace.getConfiguration('perseus');
    const pattern = new vscode.RelativePattern(path.join(root, '.perseus'), '**/*');

    watcher = vscode.workspace.createFileSystemWatcher(pattern, false, false, false);

    let debounce;
    const onChange = () => {
        clearTimeout(debounce);
        debounce = setTimeout(() => renderContext(root), 500);
    };

    watcher.onDidChange(onChange);
    watcher.onDidCreate(onChange);
    watcher.onDidDelete(onChange);

    outputChannel.appendLine('Perseus watching .perseus/ for changes');
}

async function renderContext(workspaceRoot) {
    statusBar.text = '$(sync~spin) Perseus: rendering...';
    statusBar.show();

    const perseusBin = await findPerseus();
    if (!perseusBin) {
        statusBar.text = '$(error) Perseus: not installed';
        statusBar.show();
        return;
    }

    const outputFile = resolveOutputFile(workspaceRoot);
    const contextFile = path.join(workspaceRoot, '.perseus', 'context.md');

    if (!fs.existsSync(contextFile)) {
        statusBar.text = '$(warning) Perseus: no context.md';
        statusBar.show();
        return;
    }

    return new Promise((resolve) => {
        const t0 = Date.now();
        exec(`"${perseusBin}" render "${contextFile}" --output "${outputFile}"`, 
             { cwd: workspaceRoot }, (err, stdout, stderr) => {
            const elapsed = Date.now() - t0;
            if (err) {
                outputChannel.appendLine(`Render error (${elapsed}ms): ${stderr}`);
                statusBar.text = `$(error) Perseus: render failed (${elapsed}ms)`;
            } else {
                const lines = (stdout.match(/\n/g) || []).length;
                const kb = Math.round(Buffer.byteLength(stdout, 'utf8') / 1024);
                outputChannel.appendLine(`Rendered ${lines} lines / ${kb}KB → ${outputFile} in ${elapsed}ms`);
                statusBar.text = `$(pass) Perseus: ${lines} lines · ${kb}KB · ${elapsed}ms`;
            }
            statusBar.show();
            resolve();
        });
    });
}

function resolveOutputFile(root) {
    const config = vscode.workspace.getConfiguration('perseus');
    const assistant = config.get('assistant');

    if (assistant !== 'auto') {
        return path.join(root, OUTPUT_FILES[assistant] || '.hermes.md');
    }

    // Auto-detect from workspace files
    for (const [name, file] of Object.entries(OUTPUT_FILES)) {
        if (fs.existsSync(path.join(root, file))) return path.join(root, file);
    }
    return path.join(root, config.get('outputFile') || '.hermes.md');
}

async function findPerseus() {
    return new Promise((resolve) => {
        exec('which perseus 2>/dev/null || echo ""', (err, stdout) => {
            const bin = stdout.trim();
            if (bin) return resolve(bin);
            // Fallback: check for perseus.py in workspace
            const root = vscode.workspace.workspaceFolders?.[0]?.uri?.fsPath;
            if (root && fs.existsSync(path.join(root, 'perseus.py'))) {
                return resolve('python3 ' + path.join(root, 'perseus.py'));
            }
            resolve(null);
        });
    });
}

function updateStatusBar(hasContext) {
    if (hasContext) {
        statusBar.text = '$(mirror) Perseus';
        statusBar.show();
    }
}

function deactivate() {
    if (watcher) watcher.dispose();
    if (statusBar) statusBar.dispose();
    if (outputChannel) outputChannel.dispose();
}

module.exports = { activate, deactivate };
