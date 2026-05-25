// Perseus VSCode extension — minimal LSP client.
//
// Mechanically required to live outside perseus.py because VSCode extensions
// are packaged as .vsix bundles with their own manifest, dependencies, and
// runtime (Node.js, not Python). All real logic lives in the LSP server
// (perseus.py § Phase 10.1 / task-23); this file is a thin launcher.

import * as path from 'path';
import * as vscode from 'vscode';
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
    TransportKind,
} from 'vscode-languageclient/node';

let client: LanguageClient | undefined;

export function activate(context: vscode.ExtensionContext) {
    const config = vscode.workspace.getConfiguration('perseus');
    const binary = config.get<string>('binary', 'perseus');
    const trace = config.get<string>('tracing', 'off');
    const allowMutations = config.get<boolean>('allowMutations', false);
    const serverArgs = ['serve', '--lsp', '--stdio'];
    if (allowMutations) {
        serverArgs.push('--allow-lsp-mutations');
    }

    const serverOptions: ServerOptions = {
        run: { command: binary, args: serverArgs, transport: TransportKind.stdio },
        debug: { command: binary, args: [...serverArgs], transport: TransportKind.stdio },
    };

    const clientOptions: LanguageClientOptions = {
        documentSelector: [
            { scheme: 'file', language: 'markdown' },
            { scheme: 'file', pattern: '**/AGENTS.md' },
            { scheme: 'file', pattern: '**/.perseus/context.md' },
        ],
        synchronize: {
            configurationSection: 'perseus',
            fileEvents: vscode.workspace.createFileSystemWatcher('**/.perseus/**'),
        },
        outputChannel: vscode.window.createOutputChannel('Perseus LSP'),
        traceOutputChannel: vscode.window.createOutputChannel('Perseus LSP Trace'),
    };

    client = new LanguageClient('perseus', 'Perseus', serverOptions, clientOptions);
    client.start();

    // Register VSCode-level commands that delegate to the server.
    context.subscriptions.push(
        vscode.commands.registerCommand('perseus.render', async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor || !client) {
                return;
            }
            const result: any = await client.sendRequest('workspace/executeCommand', {
                command: 'perseus.render',
                arguments: [editor.document.uri.toString()],
            });
            const out = vscode.window.createOutputChannel('Perseus Render');
            out.appendLine(result?.rendered ?? '(no output)');
            out.show(true);
        }),
        vscode.commands.registerCommand('perseus.openCheckpoint', async () => {
            if (!client) { return; }
            const result: any = await client.sendRequest('workspace/executeCommand', {
                command: 'perseus.openCheckpoint',
                arguments: [],
            });
            if (result?.uri) {
                await vscode.window.showTextDocument(vscode.Uri.parse(result.uri));
            } else {
                vscode.window.showWarningMessage('Perseus: no checkpoint found for this workspace.');
            }
        }),
        vscode.commands.registerCommand('perseus.compactMemory', async () => {
            if (!client) { return; }
            try {
                const result: any = await client.sendRequest('workspace/executeCommand', {
                    command: 'perseus.compactMemory',
                    arguments: [],
                });
                vscode.window.showInformationMessage(`Perseus: ${result?.message ?? 'compacted'}`);
            } catch (err) {
                const message = err instanceof Error ? err.message : String(err);
                vscode.window.showWarningMessage(`Perseus: ${message}`);
            }
        }),
    );

    // Status bar item — shows "Perseus: connected" when the LSP is alive.
    const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 0);
    status.text = '$(zap) Perseus';
    status.tooltip = 'Perseus LSP active';
    status.command = 'perseus.render';
    status.show();
    context.subscriptions.push(status);
}

export function deactivate(): Thenable<void> | undefined {
    if (!client) {
        return undefined;
    }
    return client.stop();
}
