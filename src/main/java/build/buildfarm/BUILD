load("@rules_java//java:java_binary.bzl", "java_binary")
load("//:jvm_flags.bzl", "add_opens_sun_nio_fs", "ensure_accurate_metadata")

package(
    default_visibility = ["//src:__subpackages__"],
)

LOGGING_RUNTIME_DEPS = [
    "@maven//:ch_qos_logback_logback_classic",
    "@maven//:ch_qos_logback_contrib_logback_json_classic",
    "@maven//:ch_qos_logback_contrib_logback_jackson",
    "@maven//:com_fasterxml_jackson_core_jackson_databind",
]

java_binary(
    name = "buildfarm-server",
    classpath_resources = [
        "//config:base_configs",
        "//config:base_properties",
    ],
    jvm_flags = ensure_accurate_metadata() + add_opens_sun_nio_fs(),
    main_class = "build.buildfarm.server.BuildFarmServer",
    visibility = ["//visibility:public"],
    runtime_deps = [
        "//src/main/java/build/buildfarm/server",
    ] + LOGGING_RUNTIME_DEPS,
)

java_binary(
    name = "buildfarm-shard-worker",
    classpath_resources = [
        "//config:base_configs",
        "//config:base_properties",
    ],
    jvm_flags = ensure_accurate_metadata() + add_opens_sun_nio_fs(),
    main_class = "build.buildfarm.worker.shard.Worker",
    visibility = ["//visibility:public"],
    runtime_deps = [
        "//src/main/java/build/buildfarm/worker/shard",
    ] + LOGGING_RUNTIME_DEPS,
)
