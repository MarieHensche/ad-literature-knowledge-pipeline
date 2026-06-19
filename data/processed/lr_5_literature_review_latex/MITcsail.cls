%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% CSAIL-style literature review class.
%% Adapted from the MIT CSAIL template shared under CC BY-SA 4.0.
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{MITcsail}[2022/05/31 MIT CSAIL Template]

\LoadClass[11pt]{article}

\RequirePackage{xcolor}
\RequirePackage{fancyhdr}
\RequirePackage{graphicx}
\RequirePackage[authoryear, sort&compress, round]{natbib}
\RequirePackage[colorlinks=true, citecolor=blue, linkcolor=black, urlcolor=blue]{hyperref}
\RequirePackage{amsmath}
\RequirePackage{amssymb}
\RequirePackage{booktabs}
\RequirePackage{caption}
\RequirePackage{mathpazo}
\RequirePackage{titlesec}

\titlelabel{\thetitle.\quad}
\captionsetup[figure]{font=small}
\captionsetup[table]{font=small}
\renewcommand*{\thefootnote}{\fnsymbol{footnote}}

\topmargin -1.0cm
\oddsidemargin -0.2cm
\textwidth 17cm
\textheight 22cm
\footskip 1cm
\setlength{\headheight}{21.25012pt}

\renewenvironment{abstract}
 {\bfseries
  \list{}{%
    \setlength{\leftmargin}{0mm}%
    \setlength{\rightmargin}{\leftmargin}%
  }%
  \item\relax}
 {\endlist}

\makeatletter
\renewcommand{\maketitle}{\bgroup\setlength{\parindent}{0pt}
\begin{flushleft}
  \textbf{\LARGE \@title}\vspace*{2.5em}

  \textbf{\@author}
\end{flushleft}\egroup
}

\pagestyle{fancy}
\fancypagestyle{firstpagestyle}{
    \fancyhf{}
    \fancyhead[L]{%
      \IfFileExists{images/CSAIL_Primary_Regular_RGB.png}{%
        \includegraphics[width=30pt]{images/CSAIL_Primary_Regular_RGB.png}%
      }{\textbf{Literature Review}}}}

\fancyhf{}
\chead{\@title}
\rfoot{\thepage}
\makeatother

\renewcommand{\figurename}{\textbf{Fig.}}
\renewcommand{\tablename}{\textbf{Table}}
\renewcommand{\thetable}{\textbf{\arabic{table}}}
\renewcommand{\thefigure}{\textbf{\arabic{figure}}}

