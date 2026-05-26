@perseus v0.8
@prompt You are a simulated mobile developer working inside a large enterprise.

@query "git log --oneline -5" @cache ttl=300
@query "gradle --version" @cache ttl=300
@query "java --version" @cache ttl=300
@query "flutter --version" @cache ttl=300
@query "dart --version" @cache ttl=300
@query "kotlin -version" @cache ttl=300
@query "xcodebuild -version" @cache ttl=300
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
@query "flutter devices" @cache ttl=300
@query "flutter doctor --verbose" @cache ttl=300
@query "flutter pub outdated --json" @cache ttl=300
@query "gradle tasks --group build" @cache ttl=300
@query "adb devices" @cache ttl=300
@query "adb shell getprop ro.build.version.sdk" @cache ttl=300
@query "adb shell dumpsys battery" @cache ttl=300
@query "xcrun simctl list devices" @cache ttl=300
@query "ls android/app/src/main/" @cache ttl=300
@query "ls ios/" @cache ttl=300
@query "ls lib/" @cache ttl=300
@query "ls test/" @cache ttl=300
@query "wc -l lib/**/*.dart 2>/dev/null" @cache ttl=300
@query "flutter analyze" @cache ttl=300
@query "dart analyze" @cache ttl=300
@query "ls -la android/gradle/wrapper/" @cache ttl=300
@query "cat gradle.properties" @cache ttl=300
@query "cat local.properties 2>/dev/null || echo no local.properties" @cache ttl=300
@query "flutter test --help | head -20" @cache ttl=300
@query "flutter build apk --debug --target-platform android-arm64" @cache ttl=300
@query "flutter build ios --no-codesign --debug" @cache ttl=300
@query "adb shell dumpsys package com.example.app" @cache ttl=300
@query "adb shell pm list packages -3" @cache ttl=300
@query "ls android/app/src/main/res/" @cache ttl=300
@query "ls -la fastlane/" @cache ttl=300
@query "cat fastlane/Fastfile" @cache ttl=300
@query "cat .firebaserc 2>/dev/null || echo no firebaserc" @cache ttl=300
@query "expr $(flutter pub outdated --json 2>/dev/null | jq .packages\|length 2>/dev/null || echo 0)" @cache ttl=300
@query "ls -la integration_test/" @cache ttl=300
@query "dart format --set-exit-if-changed lib/" @cache ttl=300
@query "flutter gen-l10n --help | head -10" @cache ttl=300
@query "ls -la .vscode/" @cache ttl=300
@query "cat .vscode/launch.json 2>/dev/null || echo no launch.json" @cache ttl=300
@query "flutter pub deps" @cache ttl=300
