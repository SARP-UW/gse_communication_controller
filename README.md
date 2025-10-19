# gse_communication_controller
communication controller software running on raspberry pi

## Repo Structure

#### src 
- #### controller: Contains core system logic. Decides what to do with incoming data and commands. Handles data processing control decision, and formatting messages before transmisison. 

- #### drivers: Contains hardware interface code for each connected device. Modular logic for reading data or controlling hardware.

- #### comms: Handles the communication layer. Manages how data is sent or received. This includes network setup, packet transmissions, and error checking.

- #### utils: General purpose helper modules. 

## Developer Setup:

### Cloning:
[Install git](https://git-scm.com/downloads)

open a terminal and init git using:
``` 
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
```
[Create an ssh key and add it to your github account.](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent)

Click the green code button in the repository menu, hit ssh option and copy the output.

open a terminal and [navigate](https://gist.github.com/bradtraversy/cc180de0edee05075a6139e42d5f28ce) to the directory where you want to clone the repository. Clone repo using ```git clone <copied from repo>```

now you can open this repo in your code editor

## virtual environment setup

install [pipenv](https://pipenv.pypa.io/en/latest/installation.html) (on mac I have found it easiest to install using [homebrew](https://brew.sh))

From the root directory, (in a terminal) run ```pipenv install``` This will install the packages detailed in the .lock file and reproduce the same environment needed to run the code.

Now when you want to run your code, from your terminal while in the root of the repo run ``` pipenv run python(3) <local path of file> ```

for example ```pipenv run python3 src/main.py```

Whenever you need a package installed you run pipenv install <package name> and it will install it and update the pipfiles accordingly.
