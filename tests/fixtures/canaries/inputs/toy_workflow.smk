# Inert supplied workflow. The canary scheduler records submissions and executes no payload.
rule all:
    input:
        expand("output/point-{point}.json", point=[0, 1, 2, 3])

rule point:
    output:
        "output/point-{point}.json"
    threads: 1
    resources:
        mem_mb=128,
        runtime=1
    shell:
        "printf '{{\"kind\":\"inert-point\",\"point\":{wildcards.point}}}' > {output}"
