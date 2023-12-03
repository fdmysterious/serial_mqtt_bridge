python_version           := "3.11"
interpreter              := ".env/bin/python" + python_version

mosquitto_container_name := "mosquitto"

test *args:
	{{interpreter}} -m pytest -vv {{args}}

pip *args:
	{{interpreter}} -m pip {{args}}

run *args:
	{{interpreter}} {{args}}


##########################################
# Mosquitto recipes
##########################################

# Start the mosquitto container
start_mosquitto:
	docker run --rm --name {{mosquitto_container_name}} -d -p 9001:9001 -p 1883:1883 -v `pwd`/mosquitto.conf:/mosquitto/config/mosquitto.conf eclipse-mosquitto

# Stop the mosquitto container
stop_mosquitto:
	docker stop {{mosquitto_container_name}}

# Check if mosquitto container is running
check_mosquitto:
	@docker ps --filter name={{mosquitto_container_name}} --format "1" | wc -l

# Ensure the mosquitto container is running, start elsewise
ensure_mosquitto:
	#!/usr/bin/sh
	mosquitto_status=`just check_mosquitto`
	if [ "$mosquitto_status" -eq 0 ] ; then
		echo "> Start mosquitto"
		just start_mosquitto
	fi

logs_mosquitto *args: ensure_mosquitto
	docker logs {{args}} {{mosquitto_container_name}} 

	
