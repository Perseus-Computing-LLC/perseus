@perseus v0.8
@prompt You are a simulated mobile developer working inside a large enterprise.

@query "git log --oneline -5" timeout=5 @cache ttl=86400
@query "gradle --version" timeout=5 @cache ttl=86400
@query "java --version" timeout=5 @cache ttl=86400
@query "flutter --version" timeout=5 @cache ttl=86400
@query "dart --version" timeout=5 @cache ttl=86400
@query "kotlin -version" timeout=5 @cache ttl=86400
@query "xcodebuild -version" timeout=5 @cache ttl=86400
@read pubspec.yaml
@read build.gradle
@read Podfile
@waypoint ttl=86400
@skills flag_stale=true
@services
  - name: emulator
    url: http://localhost:5554/
    timeout: 2
  - name: device-proxy
    url: http://localhost:8080/
    timeout: 2
@agora status=open,in_progress
@inbox
@memory focus="recent"
@health
@drift
@prefetch
@query "flutter devices" timeout=5 @cache ttl=86400
@query "flutter doctor --verbose" timeout=5 @cache ttl=86400
@query "flutter pub outdated --json" timeout=5 @cache ttl=86400
@query "gradle tasks --group build" timeout=5 @cache ttl=86400
@query "adb devices" timeout=5 @cache ttl=86400
@query "adb shell getprop ro.build.version.sdk" timeout=5 @cache ttl=86400
@query "adb shell dumpsys battery" timeout=5 @cache ttl=86400
@query "xcrun simctl list devices" timeout=5 @cache ttl=86400
@query "ls android/app/src/main/" timeout=5 @cache ttl=86400
@query "ls ios/" timeout=5 @cache ttl=86400
@query "ls lib/" timeout=5 @cache ttl=86400
@query "ls test/" timeout=5 @cache ttl=86400
@query "wc -l lib/**/*.dart 2>/dev/null" timeout=5 @cache ttl=86400
@query "flutter analyze" timeout=5 @cache ttl=86400
@query "dart analyze" timeout=5 @cache ttl=86400
@query "ls -la android/gradle/wrapper/" timeout=5 @cache ttl=86400
@query "cat gradle.properties" timeout=5 @cache ttl=86400
@query "cat local.properties 2>/dev/null || echo no local.properties" timeout=5 @cache ttl=86400
@query "flutter test --help | head -20" timeout=5 @cache ttl=86400
@query "flutter build apk --debug --target-platform android-arm64" timeout=5 @cache ttl=86400
@query "flutter build ios --no-codesign --debug" timeout=5 @cache ttl=86400
@query "adb shell dumpsys package com.example.app" timeout=5 @cache ttl=86400
@query "adb shell pm list packages -3" timeout=5 @cache ttl=86400
@query "ls android/app/src/main/res/" timeout=5 @cache ttl=86400
@query "ls -la fastlane/" timeout=5 @cache ttl=86400
@query "cat fastlane/Fastfile" timeout=5 @cache ttl=86400
@query "cat .firebaserc 2>/dev/null || echo no firebaserc" timeout=5 @cache ttl=86400
@query "expr $(flutter pub outdated --json 2>/dev/null | jq .packages\|length 2>/dev/null || echo 0)" timeout=5 @cache ttl=86400
@query "ls -la integration_test/" timeout=5 @cache ttl=86400
@query "dart format --set-exit-if-changed lib/" timeout=5 @cache ttl=86400
@query "flutter gen-l10n --help | head -10" timeout=5 @cache ttl=86400
@query "ls -la .vscode/" timeout=5 @cache ttl=86400
@query "cat .vscode/launch.json 2>/dev/null || echo no launch.json" timeout=5 @cache ttl=86400
@query "flutter pub deps" timeout=5 @cache ttl=86400
